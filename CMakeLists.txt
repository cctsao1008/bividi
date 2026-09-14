cmake_minimum_required(VERSION 3.20)

project(bividi LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(BIVIDI_WITH_OPENCV "Build the OpenCV zero-copy image bridge when OpenCV is available" ON)
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
        message(STATUS "OpenCV not found; building dependency-light Bividi core only")
    endif()
endif()

if(BIVIDI_BUILD_TESTS)
    enable_testing()
    add_executable(bividi_native_tests tests/native/test_decxin.cpp)
    target_link_libraries(bividi_native_tests PRIVATE bividi_core)
    add_test(NAME bividi_native_tests COMMAND bividi_native_tests)
endif()
