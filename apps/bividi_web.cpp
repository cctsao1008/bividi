#include "bividi/session.hpp"

#ifdef BIVIDI_HAVE_NORI_SESSION
#include "bividi/nori_session.hpp"
#endif

#include <opencv2/core.hpp>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <memory>
#include <sstream>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

#ifdef _WIN32
#define NOMINMAX
#include <winsock2.h>
#include <ws2tcpip.h>
using socket_t = SOCKET;
constexpr socket_t kInvalidSocket = INVALID_SOCKET;
#else
#include <arpa/inet.h>
#include <csignal>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>
using socket_t = int;
constexpr socket_t kInvalidSocket = -1;
#endif

#ifndef BIVIDI_WEB_ROOT
#define BIVIDI_WEB_ROOT "web"
#endif

namespace {

constexpr int kPreviewWidth = 640;
constexpr int kPreviewHeight = 400;
constexpr int kPreviewFps = 20;

const char* capture_state_name(bividi::CaptureState state) noexcept {
    switch (state) {
        case bividi::CaptureState::idle: return "idle";
        case bividi::CaptureState::running: return "streaming";
        case bividi::CaptureState::paused: return "paused";
        case bividi::CaptureState::disconnected: return "disconnected";
        case bividi::CaptureState::error: return "error";
    }
    return "unknown";
}

std::string json_escape(const std::string& value) {
    std::ostringstream out;
    for (const char ch : value) {
        switch (ch) {
            case '\\': out << "\\\\"; break;
            case '"': out << "\\\""; break;
            case '\n': out << "\\n"; break;
            case '\r': out << "\\r"; break;
            case '\t': out << "\\t"; break;
            default: out << ch; break;
        }
    }
    return out.str();
}

std::uint32_t parse_u32(const char* value, const char* name) {
    try {
        std::size_t used = 0;
        const auto parsed = std::stoul(value, &used, 10);
        if (value[used] != '\0' || parsed > 0xffffffffUL) {
            throw std::out_of_range("range");
        }
        return static_cast<std::uint32_t>(parsed);
    } catch (...) {
        std::cerr << "invalid " << name << ": " << value << '\n';
        std::exit(2);
    }
}

cv::Mat render_synthetic_camera(const bividi::SessionStatus& state, bool camera_b) {
    cv::Mat image(kPreviewHeight, kPreviewWidth, CV_8UC3, cv::Scalar(27, 30, 35));
    const int disparity = camera_b ? -26 : 26;
    const int direction = camera_b ? -1 : 1;
    const int x = static_cast<int>((state.capture.frames * 5) % (kPreviewWidth - 180)) + 90 + disparity;
    const int y = kPreviewHeight / 2 + static_cast<int>(60.0 * std::sin(state.capture.frames * 0.055));

    cv::rectangle(image, cv::Rect(34, 58, kPreviewWidth - 68, kPreviewHeight - 116), cv::Scalar(72, 76, 82), 2);
    cv::line(image, cv::Point(kPreviewWidth / 2, 58), cv::Point(kPreviewWidth / 2, kPreviewHeight - 58), cv::Scalar(54, 58, 64), 1);
    cv::circle(image, cv::Point(std::clamp(x, 40, kPreviewWidth - 40), y), 34, cv::Scalar(220, 220, 220), -1, cv::LINE_AA);
    cv::circle(image, cv::Point(std::clamp(x + direction * 9, 40, kPreviewWidth - 40), y), 13, cv::Scalar(44, 46, 50), -1, cv::LINE_AA);

    const double brightness = std::clamp(
        0.38 + state.exposure_us / 22000.0 + state.gain_x10 / 650.0,
        0.38,
        1.35);
    image.convertTo(image, -1, brightness, 0.0);

    cv::putText(
        image,
        camera_b ? "Camera B - synthetic preview" : "Camera A - synthetic preview",
        cv::Point(24, 36),
        cv::FONT_HERSHEY_SIMPLEX,
        0.68,
        cv::Scalar(238, 238, 238),
        2,
        cv::LINE_AA);
    return image;
}

cv::Mat render_live_camera(const bividi::ImageView& view, bool camera_b) {
    if (view.empty() || view.pixel_format != bividi::PixelFormat::bgr24 || view.bytes_per_pixel != 3) {
        return {};
    }

    cv::Mat source(
        static_cast<int>(view.height),
        static_cast<int>(view.width),
        CV_8UC3,
        const_cast<std::uint8_t*>(view.data),
        view.row_stride);
    const double scale = std::min(
        static_cast<double>(kPreviewWidth) / static_cast<double>(view.width),
        static_cast<double>(kPreviewHeight) / static_cast<double>(view.height));
    const int width = std::max(1, static_cast<int>(std::lround(view.width * scale)));
    const int height = std::max(1, static_cast<int>(std::lround(view.height * scale)));

    cv::Mat resized;
    cv::resize(source, resized, cv::Size(width, height), 0.0, 0.0, cv::INTER_AREA);
    cv::Mat canvas(kPreviewHeight, kPreviewWidth, CV_8UC3, cv::Scalar(16, 18, 20));
    const int x = (kPreviewWidth - width) / 2;
    const int y = (kPreviewHeight - height) / 2;
    resized.copyTo(canvas(cv::Rect(x, y, width, height)));
    cv::putText(
        canvas,
        camera_b ? "Camera B - live" : "Camera A - live",
        cv::Point(24, 36),
        cv::FONT_HERSHEY_SIMPLEX,
        0.68,
        cv::Scalar(238, 238, 238),
        2,
        cv::LINE_AA);
    return canvas;
}

cv::Mat render_waiting_camera(const bividi::SessionStatus& state, bool camera_b) {
    cv::Mat image(kPreviewHeight, kPreviewWidth, CV_8UC3, cv::Scalar(22, 24, 28));
    cv::putText(
        image,
        camera_b ? "Camera B - waiting for live frame" : "Camera A - waiting for live frame",
        cv::Point(32, kPreviewHeight / 2 - 10),
        cv::FONT_HERSHEY_SIMPLEX,
        0.60,
        cv::Scalar(220, 220, 220),
        1,
        cv::LINE_AA);
    cv::putText(
        image,
        state.last_action,
        cv::Point(32, kPreviewHeight / 2 + 26),
        cv::FONT_HERSHEY_SIMPLEX,
        0.44,
        cv::Scalar(165, 170, 178),
        1,
        cv::LINE_AA);
    return image;
}

cv::Mat render_camera(bividi::CaptureSession& session, bool camera_b) {
    const auto state = session.snapshot();
    bividi::StereoPreviewFrame preview;
    if (session.latest_stereo_preview(preview)) {
        auto image = render_live_camera(camera_b ? preview.camera_b : preview.camera_a, camera_b);
        if (!image.empty()) return image;
    }
    if (state.source_id == "synthetic") return render_synthetic_camera(state, camera_b);
    return render_waiting_camera(state, camera_b);
}

std::vector<unsigned char> encode_jpeg(bividi::CaptureSession& session, bool camera_b) {
    std::vector<unsigned char> encoded;
    const std::vector<int> params{cv::IMWRITE_JPEG_QUALITY, 82};
    if (!cv::imencode(".jpg", render_camera(session, camera_b), encoded, params)) {
        encoded.clear();
    }
    return encoded;
}

std::string json_status(const bividi::SessionStatus& s) {
    std::ostringstream out;
    out << "{"
        << "\"source\":\"" << json_escape(s.source_id) << "\","
        << "\"state\":\"" << capture_state_name(s.capture.state) << "\","
        << "\"frame_count\":" << s.capture.frames << ","
        << "\"drops\":" << s.capture.drops << ","
        << "\"duplicates\":" << s.capture.duplicates << ","
        << "\"out_of_order\":" << s.capture.out_of_order << ","
        << "\"acquisition_fps_nominal\":" << s.nominal_fps << ","
        << "\"acquisition_fps_measured\":" << s.fps << ","
        << "\"preview_fps\":" << kPreviewFps << ","
        << "\"preview_width\":" << kPreviewWidth << ","
        << "\"preview_height\":" << kPreviewHeight << ","
        << "\"exposure_us\":" << s.exposure_us << ","
        << "\"gain_x10\":" << s.gain_x10 << ","
        << "\"trigger\":\"" << bividi::trigger_mode_name(s.trigger_mode) << "\","
        << "\"exposure_start_us\":" << s.exposure_start_us << ","
        << "\"exposure_end_us\":" << s.exposure_end_us << ","
        << "\"imu_rate_hz\":" << s.imu_rate_hz << ","
        << "\"last_action\":\"" << json_escape(s.last_action) << "\""
        << "}";
    return out.str();
}

std::string read_text_file(const std::string& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) return {};
    std::ostringstream out;
    out << input.rdbuf();
    return out.str();
}

void close_socket(socket_t s) {
#ifdef _WIN32
    closesocket(s);
#else
    close(s);
#endif
}

bool send_all(socket_t s, const void* data, std::size_t size) {
    const auto* bytes = static_cast<const char*>(data);
    while (size > 0) {
#ifdef _WIN32
        const int sent = send(s, bytes, static_cast<int>(size), 0);
#else
        const auto sent = send(s, bytes, size, MSG_NOSIGNAL);
#endif
        if (sent <= 0) return false;
        bytes += sent;
        size -= static_cast<std::size_t>(sent);
    }
    return true;
}

bool send_text(socket_t s, const std::string& text) {
    return send_all(s, text.data(), text.size());
}

void send_response(socket_t s, int code, const char* reason, const char* content_type, const std::string& body) {
    std::ostringstream headers;
    headers << "HTTP/1.1 " << code << ' ' << reason << "\r\n"
            << "Content-Type: " << content_type << "\r\n"
            << "Content-Length: " << body.size() << "\r\n"
            << "Cache-Control: no-store\r\n"
            << "Connection: close\r\n\r\n";
    send_text(s, headers.str());
    send_text(s, body);
}

void send_binary(socket_t s, const char* content_type, const std::vector<unsigned char>& body) {
    std::ostringstream headers;
    headers << "HTTP/1.1 200 OK\r\n"
            << "Content-Type: " << content_type << "\r\n"
            << "Content-Length: " << body.size() << "\r\n"
            << "Cache-Control: no-store\r\n"
            << "Connection: close\r\n\r\n";
    if (!send_text(s, headers.str())) return;
    if (!body.empty()) send_all(s, body.data(), body.size());
}

std::unordered_map<std::string, std::string> parse_query(const std::string& path) {
    std::unordered_map<std::string, std::string> result;
    const auto pos = path.find('?');
    if (pos == std::string::npos) return result;
    std::istringstream items(path.substr(pos + 1));
    std::string item;
    while (std::getline(items, item, '&')) {
        const auto eq = item.find('=');
        if (eq != std::string::npos) result[item.substr(0, eq)] = item.substr(eq + 1);
    }
    return result;
}

std::string route_only(const std::string& path) {
    const auto pos = path.find('?');
    return pos == std::string::npos ? path : path.substr(0, pos);
}

bool parse_int_query(const std::string& path, const char* name, int& out) {
    const auto query = parse_query(path);
    const auto it = query.find(name);
    if (it == query.end()) return false;
    try {
        std::size_t used = 0;
        const int value = std::stoi(it->second, &used);
        if (used != it->second.size()) return false;
        out = value;
        return true;
    } catch (...) {
        return false;
    }
}

void stream_mjpeg(socket_t s, bividi::CaptureSession& session, bool camera_b) {
    const std::string headers =
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: multipart/x-mixed-replace; boundary=frame\r\n"
        "Cache-Control: no-store, no-cache, must-revalidate\r\n"
        "Pragma: no-cache\r\n"
        "Connection: close\r\n\r\n";
    if (!send_text(s, headers)) return;

    while (true) {
        const auto jpeg = encode_jpeg(session, camera_b);
        if (jpeg.empty()) return;
        std::ostringstream part;
        part << "--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " << jpeg.size() << "\r\n\r\n";
        if (!send_text(s, part.str())) return;
        if (!send_all(s, jpeg.data(), jpeg.size())) return;
        if (!send_text(s, "\r\n")) return;
        std::this_thread::sleep_for(std::chrono::milliseconds(1000 / kPreviewFps));
    }
}

void handle_client(socket_t client, bividi::CaptureSession& session) {
    std::string request(8192, '\0');
#ifdef _WIN32
    const int received = recv(client, request.data(), static_cast<int>(request.size()), 0);
#else
    const auto received = recv(client, request.data(), request.size(), 0);
#endif
    if (received <= 0) {
        close_socket(client);
        return;
    }
    request.resize(static_cast<std::size_t>(received));

    std::istringstream first_line(request.substr(0, request.find("\r\n")));
    std::string method;
    std::string path;
    std::string version;
    first_line >> method >> path >> version;
    const auto route = route_only(path);

    if (method == "GET" && route == "/") {
        const auto body = read_text_file(std::string(BIVIDI_WEB_ROOT) + "/index.html");
        send_response(client, body.empty() ? 500 : 200, body.empty() ? "Internal Server Error" : "OK", "text/html; charset=utf-8", body.empty() ? "missing web/index.html" : body);
    } else if (method == "GET" && route == "/app.js") {
        const auto body = read_text_file(std::string(BIVIDI_WEB_ROOT) + "/app.js");
        send_response(client, body.empty() ? 500 : 200, body.empty() ? "Internal Server Error" : "OK", "application/javascript; charset=utf-8", body.empty() ? "missing web/app.js" : body);
    } else if (method == "GET" && route == "/style.css") {
        const auto body = read_text_file(std::string(BIVIDI_WEB_ROOT) + "/style.css");
        send_response(client, body.empty() ? 500 : 200, body.empty() ? "Internal Server Error" : "OK", "text/css; charset=utf-8", body.empty() ? "missing web/style.css" : body);
    } else if (method == "GET" && route == "/api/status") {
        send_response(client, 200, "OK", "application/json", json_status(session.snapshot()));
    } else if (method == "POST" && route == "/api/capture/toggle") {
        session.toggle_capture();
        send_response(client, 200, "OK", "application/json", json_status(session.snapshot()));
    } else if (method == "POST" && route == "/api/trigger/cycle") {
        session.cycle_trigger();
        send_response(client, 200, "OK", "application/json", json_status(session.snapshot()));
    } else if (method == "POST" && route == "/api/reconnect") {
        session.reconnect();
        send_response(client, 200, "OK", "application/json", json_status(session.snapshot()));
    } else if (method == "POST" && route == "/api/exposure") {
        int value = 0;
        if (!parse_int_query(path, "value", value)) {
            send_response(client, 400, "Bad Request", "text/plain", "missing or invalid value");
        } else if (!session.set_exposure_us(value)) {
            send_response(client, 400, "Bad Request", "text/plain", "exposure value rejected");
        } else {
            send_response(client, 200, "OK", "application/json", json_status(session.snapshot()));
        }
    } else if (method == "POST" && route == "/api/gain") {
        int value = 0;
        if (!parse_int_query(path, "value", value)) {
            send_response(client, 400, "Bad Request", "text/plain", "missing or invalid value");
        } else if (!session.set_gain_x10(value)) {
            send_response(client, 400, "Bad Request", "text/plain", "gain value rejected");
        } else {
            send_response(client, 200, "OK", "application/json", json_status(session.snapshot()));
        }
    } else if (method == "GET" && (route == "/snapshot/a.jpg" || route == "/snapshot/b.jpg")) {
        send_binary(client, "image/jpeg", encode_jpeg(session, route.find("/b.jpg") != std::string::npos));
    } else if (method == "GET" && (route == "/stream/a.mjpg" || route == "/stream/b.mjpg")) {
        stream_mjpeg(client, session, route.find("/b.mjpg") != std::string::npos);
    } else {
        send_response(client, 404, "Not Found", "text/plain", "not found");
    }

    close_socket(client);
}

bool is_loopback(const std::string& address) {
    return address == "127.0.0.1" || address == "127.0.0.0" || address == "::1";
}

std::unique_ptr<bividi::CaptureSession> make_session(
    const std::string& source,
    std::uint32_t device,
    std::uint32_t mode,
    std::uint32_t timeout_ms) {
    if (source == "synthetic") {
        return std::make_unique<bividi::SyntheticCaptureSession>();
    }
    if (source == "nori") {
#ifdef BIVIDI_HAVE_NORI_SESSION
        bividi::nori::NoriSessionConfig config{};
        config.stream.device_index = device;
        config.stream.mode_index = mode;
        config.stream.timeout_ms = timeout_ms;
        return std::make_unique<bividi::nori::NoriCaptureSession>(config);
#else
        throw std::runtime_error("Nori source was requested but this build does not include the Nori SDK session backend");
#endif
    }
    throw std::runtime_error("unknown web source: " + source);
}

int self_test() {
    bividi::SyntheticCaptureSession session;
    std::this_thread::sleep_for(std::chrono::milliseconds(40));
    auto status = session.snapshot();
    const auto a = encode_jpeg(session, false);
    const auto b = encode_jpeg(session, true);
    const auto json = json_status(status);
    if (a.empty() || b.empty() || json.find("\"source\":\"synthetic\"") == std::string::npos) {
        std::cerr << "bividi-web self-test: render/status failure\n";
        return 1;
    }

    session.toggle_capture();
    session.set_exposure_us(8123);
    session.set_gain_x10(37);
    session.cycle_trigger();
    status = session.snapshot();
    if (status.running() ||
        status.exposure_us != 8123 ||
        status.gain_x10 != 37 ||
        status.trigger_mode != bividi::TriggerMode::software) {
        std::cerr << "bividi-web self-test: control failure\n";
        return 2;
    }

    const auto index = read_text_file(std::string(BIVIDI_WEB_ROOT) + "/index.html");
    const auto app = read_text_file(std::string(BIVIDI_WEB_ROOT) + "/app.js");
    const auto css = read_text_file(std::string(BIVIDI_WEB_ROOT) + "/style.css");
    if (index.empty() || app.empty() || css.empty()) {
        std::cerr << "bividi-web self-test: static assets missing\n";
        return 3;
    }

    std::cout << "bividi-web self-test: PASS\n"
              << "jpeg_a=" << a.size() << " jpeg_b=" << b.size() << " static_assets=3\n";
    return 0;
}

bool initialize_sockets() {
#ifdef _WIN32
    WSADATA data{};
    return WSAStartup(MAKEWORD(2, 2), &data) == 0;
#else
    std::signal(SIGPIPE, SIG_IGN);
    return true;
#endif
}

void cleanup_sockets() {
#ifdef _WIN32
    WSACleanup();
#endif
}

int run_server(
    const std::string& listen_address,
    int port,
    const std::string& source,
    std::uint32_t device,
    std::uint32_t mode,
    std::uint32_t timeout_ms) {
    std::unique_ptr<bividi::CaptureSession> session;
    try {
        session = make_session(source, device, mode, timeout_ms);
    } catch (const std::exception& error) {
        std::cerr << "bividi-web: " << error.what() << '\n';
        return 2;
    }

    if (!initialize_sockets()) {
        std::cerr << "bividi-web: socket initialization failed\n";
        return 3;
    }

    socket_t server = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (server == kInvalidSocket) {
        std::cerr << "bividi-web: socket creation failed\n";
        cleanup_sockets();
        return 4;
    }

    int reuse = 1;
#ifdef _WIN32
    setsockopt(server, SOL_SOCKET, SO_REUSEADDR, reinterpret_cast<const char*>(&reuse), sizeof(reuse));
#else
    setsockopt(server, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));
#endif

    sockaddr_in address{};
    address.sin_family = AF_INET;
    address.sin_port = htons(static_cast<std::uint16_t>(port));
    if (inet_pton(AF_INET, listen_address.c_str(), &address.sin_addr) != 1) {
        std::cerr << "bividi-web: --listen currently expects a numeric IPv4 address\n";
        close_socket(server);
        cleanup_sockets();
        return 5;
    }

    if (bind(server, reinterpret_cast<sockaddr*>(&address), sizeof(address)) != 0 || listen(server, 16) != 0) {
        std::cerr << "bividi-web: bind/listen failed on " << listen_address << ':' << port << "\n";
        close_socket(server);
        cleanup_sockets();
        return 6;
    }

    std::cout << "Bividi Web UI: http://" << listen_address << ':' << port << "\n";
    std::cout << "source=" << source << " preview=" << kPreviewWidth << 'x' << kPreviewHeight << '@' << kPreviewFps << "fps";
    if (source == "nori") std::cout << " device=" << device << " mode=" << mode;
    std::cout << '\n';
    if (!is_loopback(listen_address)) {
        std::cout << "WARNING: non-loopback bind exposes the engineering control surface to the network.\n";
    }

    while (true) {
        sockaddr_in client_address{};
#ifdef _WIN32
        int client_length = sizeof(client_address);
#else
        socklen_t client_length = sizeof(client_address);
#endif
        socket_t client = accept(server, reinterpret_cast<sockaddr*>(&client_address), &client_length);
        if (client == kInvalidSocket) continue;
        std::thread(handle_client, client, std::ref(*session)).detach();
    }
}

}  // namespace

int main(int argc, char** argv) {
    std::string listen_address = "127.0.0.1";
    int port = 8080;
    std::string source = "synthetic";
    std::uint32_t device = 0;
    std::uint32_t mode = 0;
    std::uint32_t timeout_ms = 2000;

    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        if (arg == "--self-test") return self_test();
        if (arg == "--help") {
            std::cout << "bividi-web [--listen 127.0.0.1] [--port 8080] [--source synthetic|nori] [--device N] [--mode N] [--timeout-ms N] [--self-test]\n";
            return 0;
        }
        if (arg == "--listen" && i + 1 < argc) {
            listen_address = argv[++i];
        } else if (arg == "--port" && i + 1 < argc) {
            port = std::stoi(argv[++i]);
        } else if (arg == "--source" && i + 1 < argc) {
            source = argv[++i];
        } else if (arg == "--device" && i + 1 < argc) {
            device = parse_u32(argv[++i], "device index");
        } else if (arg == "--mode" && i + 1 < argc) {
            mode = parse_u32(argv[++i], "mode index");
        } else if (arg == "--timeout-ms" && i + 1 < argc) {
            timeout_ms = parse_u32(argv[++i], "timeout");
        } else {
            std::cerr << "unknown/incomplete option: " << arg << '\n';
            return 2;
        }
    }

    if (port < 1 || port > 65535) {
        std::cerr << "bividi-web: port must be 1..65535\n";
        return 1;
    }
    return run_server(listen_address, port, source, device, mode, timeout_ms);
}
