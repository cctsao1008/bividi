cmake_minimum_required(VERSION 3.20)

project(bividi LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(BIVIDI_WITH_OPENCV "Build the OpenCV zero-copy image bridge when OpenCV is available" ON)
option(BIVIDI_WITH_NORI_SDK "Build the optional DECXIN/Nori vendor-SDK backend surface" OFF)
option(BIVIDI_BUILD_VIEWER "Build the OpenCV HighGUI engineering viewer when dependencies are available" ON)
option(BIVIDI_BUILD_WEB "Build the lightweight browser engineering console when dependencies are available" ON)
option(BIVIDI_BUILD_TESTS "Build hardware-independent native tests" ON)
set(BIVIDI_NORI_SDK_ROOT "" CACHE PATH "Path to the supplied Nori_Xvision SDK root")
set(BIVIDI_NORI_LIBRARY "" CACHE FILEPATH "Optional explicit path to the Nori_Xvision vendor library")

find_package(Threads REQUIRED)

add_library(bividi_core STATIC
    src/native/characterization.cpp
    src/native/decxin.cpp
    src/native/session.cpp
)
target_include_directories(bividi_core PUBLIC include)
target_link_libraries(bividi_core PUBLIC Threads::Threads)
target_compile_features(bividi_core PUBLIC cxx_std_17)

if(BIVIDI_WITH_NORI_SDK)
    if(NOT BIVIDI_NORI_SDK_ROOT)
        message(FATAL_ERROR "BIVIDI_WITH_NORI_SDK=ON requires BIVIDI_NORI_SDK_ROOT")
    endif()

    set(_bividi_nori_include "${BIVIDI_NORI_SDK_ROOT}/Includes/Nori_Xvision_API")
    if(NOT EXISTS "${_bividi_nori_include}/Nori_Xvision_API.h")
        message(FATAL_ERROR "Nori_Xvision_API.h not found under ${_bividi_nori_include}")
    endif()

    if(NOT BIVIDI_NORI_LIBRARY)
        if(WIN32)
            if(CMAKE_SIZEOF_VOID_P EQUAL 8)
                set(_bividi_nori_library "${BIVIDI_NORI_SDK_ROOT}/Libraries/win64/Nori_Xvision_API_x64.lib")
            else()
                set(_bividi_nori_library "${BIVIDI_NORI_SDK_ROOT}/Libraries/win32/Nori_Xvision_API.lib")
            endif()
        elseif(UNIX)
            string(TOLOWER "${CMAKE_SYSTEM_PROCESSOR}" _bividi_processor)
            if(_bividi_processor MATCHES "^(x86_64|amd64)$")
                set(_bividi_nori_arch x64)
            elseif(_bividi_processor MATCHES "^(x86|i[3-6]86)$")
                set(_bividi_nori_arch x86)
            elseif(_bividi_processor MATCHES "^(aarch64|arm64)$")
                set(_bividi_nori_arch arm64)
            elseif(_bividi_processor MATCHES "^(arm|armv7|armv7l)$")
                set(_bividi_nori_arch arm32)
            else()
                message(FATAL_ERROR "Unsupported Nori SDK processor '${CMAKE_SYSTEM_PROCESSOR}'; set BIVIDI_NORI_LIBRARY explicitly")
            endif()
            set(_bividi_nori_library "${BIVIDI_NORI_SDK_ROOT}/Libraries/${_bividi_nori_arch}/libNori_Xvision_Std.so")
        else()
            message(FATAL_ERROR "Nori SDK backend currently supports Windows and Linux")
        endif()
    else()
        set(_bividi_nori_library "${BIVIDI_NORI_LIBRARY}")
    endif()

    if(NOT EXISTS "${_bividi_nori_library}")
        message(FATAL_ERROR "Nori vendor library not found: ${_bividi_nori_library}")
    endif()

    add_library(bividi_nori STATIC
        src/native/nori_probe.cpp
        src/native/nori_stream.cpp
    )
    target_include_directories(bividi_nori
        PUBLIC include
        PRIVATE "${_bividi_nori_include}"
    )
    target_link_libraries(bividi_nori PUBLIC bividi_core PRIVATE "${_bividi_nori_library}")
    target_compile_features(bividi_nori PUBLIC cxx_std_17)

    add_executable(bividi-nori-probe apps/bividi_nori_probe.cpp)
    target_link_libraries(bividi-nori-probe PRIVATE bividi_nori)
    target_compile_features(bividi-nori-probe PRIVATE cxx_std_17)

    add_executable(bividi-nori-grab apps/bividi_nori_grab.cpp)
    target_link_libraries(bividi-nori-grab PRIVATE bividi_nori)
    target_compile_features(bividi-nori-grab PRIVATE cxx_std_17)

    message(STATUS "Bividi Nori SDK probe/pull stream enabled: ${_bividi_nori_library}")
endif()

if(BIVIDI_WITH_OPENCV)
    find_package(OpenCV QUIET COMPONENTS core)
    if(OpenCV_FOUND)
        add_library(bividi_opencv STATIC
            src/native/opencv.cpp
        )
        target_include_directories(bividi_opencv PUBLIC include ${OpenCV_INCLUDE_DIRS})
        target_link_libraries(bividi_opencv PUBLIC bividi_core ${OpenCV_LIBS})
        target_compile_features(bividi_opencv PUBLIC cxx_std_17)
        message(STATUS "Bividi OpenCV bridge enabled")
    else()
        message(STATUS "OpenCV core not found; building dependency-light Bividi core only")
    endif()

    find_package(OpenCV QUIET COMPONENTS core imgproc imgcodecs)
    if(OpenCV_FOUND)
        add_library(bividi_nori_opencv STATIC
            src/native/nori_opencv.cpp
            src/native/nori_decxin.cpp
        )
        target_include_directories(bividi_nori_opencv PUBLIC include ${OpenCV_INCLUDE_DIRS})
        target_link_libraries(bividi_nori_opencv PUBLIC bividi_core ${OpenCV_LIBS})
        target_compile_features(bividi_nori_opencv PUBLIC cxx_std_17)
        message(STATUS "Bividi Nori transport normalization + DECXIN pipeline enabled")
    else()
        message(STATUS "OpenCV imgproc/imgcodecs not found; Nori transport normalization disabled")
    endif()
endif()

if(BIVIDI_WITH_NORI_SDK AND TARGET bividi_nori AND TARGET bividi_nori_opencv)
    add_library(bividi_nori_session STATIC
        src/native/nori_session.cpp
    )
    target_include_directories(bividi_nori_session PUBLIC include)
    target_link_libraries(bividi_nori_session PUBLIC bividi_nori bividi_nori_opencv)
    target_compile_features(bividi_nori_session PUBLIC cxx_std_17)

    add_executable(bividi-nori-decode apps/bividi_nori_decode.cpp)
    target_link_libraries(bividi-nori-decode PRIVATE bividi_nori bividi_nori_opencv)
    target_compile_features(bividi-nori-decode PRIVATE cxx_std_17)

    add_executable(bividi-nori-characterize apps/bividi_nori_characterize.cpp)
    target_link_libraries(bividi-nori-characterize PRIVATE bividi_nori bividi_nori_opencv)
    target_compile_features(bividi-nori-characterize PRIVATE cxx_std_17)

    message(STATUS "Bividi Nori live DECXIN decode/session/characterization surface enabled")
endif()

if(BIVIDI_BUILD_VIEWER)
    find_package(OpenCV QUIET COMPONENTS core highgui imgproc imgcodecs)
    if(OpenCV_FOUND)
        add_executable(bividi-viewer apps/bividi_viewer.cpp)
        target_include_directories(bividi-viewer PRIVATE include ${OpenCV_INCLUDE_DIRS})
        target_link_libraries(bividi-viewer PRIVATE bividi_core ${OpenCV_LIBS})
        if(TARGET bividi_nori_session)
            target_link_libraries(bividi-viewer PRIVATE bividi_nori_session)
            target_compile_definitions(bividi-viewer PRIVATE BIVIDI_HAVE_NORI_SESSION=1)
        endif()
        target_compile_features(bividi-viewer PRIVATE cxx_std_17)
        message(STATUS "Bividi engineering viewer enabled")
    else()
        message(STATUS "OpenCV HighGUI/imgproc/imgcodecs not found; bividi-viewer disabled")
    endif()
endif()

if(BIVIDI_BUILD_WEB)
    find_package(OpenCV QUIET COMPONENTS core imgproc imgcodecs)
    if(OpenCV_FOUND)
        add_executable(bividi-web apps/bividi_web.cpp)
        target_include_directories(bividi-web PRIVATE include ${OpenCV_INCLUDE_DIRS})
        target_link_libraries(bividi-web PRIVATE bividi_core ${OpenCV_LIBS})
        if(TARGET bividi_nori_session)
            target_link_libraries(bividi-web PRIVATE bividi_nori_session)
            target_compile_definitions(bividi-web PRIVATE BIVIDI_HAVE_NORI_SESSION=1)
        endif()
        target_compile_features(bividi-web PRIVATE cxx_std_17)
        target_compile_definitions(bividi-web PRIVATE BIVIDI_WEB_ROOT="${CMAKE_CURRENT_SOURCE_DIR}/web")
        if(WIN32)
            target_link_libraries(bividi-web PRIVATE ws2_32)
        endif()
        message(STATUS "Bividi browser engineering console enabled")
    else()
        message(STATUS "OpenCV core/imgproc/imgcodecs not found; bividi-web disabled")
    endif()
endif()

if(BIVIDI_BUILD_TESTS)
    enable_testing()

    add_executable(bividi_native_tests tests/native/test_decxin.cpp)
    target_link_libraries(bividi_native_tests PRIVATE bividi_core)
    add_test(NAME bividi_native_tests COMMAND bividi_native_tests)

    add_executable(bividi_capture_tests tests/native/test_capture.cpp)
    target_link_libraries(bividi_capture_tests PRIVATE bividi_core)
    add_test(NAME bividi_capture_tests COMMAND bividi_capture_tests)

    add_executable(bividi_session_tests tests/native/test_session.cpp)
    target_link_libraries(bividi_session_tests PRIVATE bividi_core)
    add_test(NAME bividi_session_tests COMMAND bividi_session_tests)

    add_executable(bividi_characterization_tests tests/native/test_characterization.cpp)
    target_link_libraries(bividi_characterization_tests PRIVATE bividi_core)
    add_test(NAME bividi_characterization_tests COMMAND bividi_characterization_tests)

    if(TARGET bividi_opencv)
        add_executable(bividi_opencv_tests tests/native/test_opencv.cpp)
        target_link_libraries(bividi_opencv_tests PRIVATE bividi_opencv)
        add_test(NAME bividi_opencv_tests COMMAND bividi_opencv_tests)
    endif()

    if(TARGET bividi_nori_opencv)
        add_executable(bividi_nori_opencv_tests tests/native/test_nori_opencv.cpp)
        target_link_libraries(bividi_nori_opencv_tests PRIVATE bividi_nori_opencv)
        add_test(NAME bividi_nori_opencv_tests COMMAND bividi_nori_opencv_tests)

        add_executable(bividi_nori_decxin_tests tests/native/test_nori_decxin.cpp)
        target_link_libraries(bividi_nori_decxin_tests PRIVATE bividi_nori_opencv)
        add_test(NAME bividi_nori_decxin_tests COMMAND bividi_nori_decxin_tests)
    endif()

    if(TARGET bividi-viewer)
        add_test(NAME bividi_viewer_self_test COMMAND bividi-viewer --self-test)
    endif()

    if(TARGET bividi-web)
        add_test(NAME bividi_web_self_test COMMAND bividi-web --self-test)
    endif()
endif()
