cmake_minimum_required(VERSION 3.20)

project(bividi LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(BIVIDI_WITH_OPENCV "Build the OpenCV zero-copy image bridge when OpenCV is available" ON)
option(BIVIDI_BUILD_VIEWER "Build the OpenCV HighGUI engineering viewer when dependencies are available" ON)
option(BIVIDI_BUILD_WEB "Build the lightweight browser engineering console when dependencies are available" ON)
option(BIVIDI_BUILD_TESTS "Build hardware-independent native tests" ON)

add_library(bividi_core STATIC
    src/native/decxin.cpp
)
target_include_directories(bividi_core PUBLIC include)
target_compile_features(bividi_core PUBLIC cxx_std_17)

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
endif()

if(BIVIDI_BUILD_VIEWER)
    find_package(OpenCV QUIET COMPONENTS core highgui imgproc imgcodecs)
    if(OpenCV_FOUND)
        add_executable(bividi-viewer apps/bividi_viewer.cpp)
        target_include_directories(bividi-viewer PRIVATE include ${OpenCV_INCLUDE_DIRS})
        target_link_libraries(bividi-viewer PRIVATE bividi_core ${OpenCV_LIBS})
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

    if(TARGET bividi_opencv)
        add_executable(bividi_opencv_tests tests/native/test_opencv.cpp)
        target_link_libraries(bividi_opencv_tests PRIVATE bividi_opencv)
        add_test(NAME bividi_opencv_tests COMMAND bividi_opencv_tests)
    endif()

    if(TARGET bividi-viewer)
        add_test(NAME bividi_viewer_self_test COMMAND bividi-viewer --self-test)
    endif()

    if(TARGET bividi-web)
        add_test(NAME bividi_web_self_test COMMAND bividi-web --self-test)
    endif()
endif()
