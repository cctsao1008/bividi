cmake_minimum_required(VERSION 3.20)
project(bividi_kimera_external_probe LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

set(BIVIDI_KIMERA_VIO_REVISION "" CACHE STRING
    "Exact Kimera-VIO git revision asserted for this external package")

include(${CMAKE_CURRENT_LIST_DIR}/../BividiKimeraExternal.cmake)

add_executable(bividi-kimera-link-probe
    ${CMAKE_CURRENT_LIST_DIR}/../../apps/bividi_kimera_link_probe.cpp
)
target_link_libraries(bividi-kimera-link-probe PRIVATE ${BIVIDI_KIMERA_VIO_TARGET})
target_compile_features(bividi-kimera-link-probe PRIVATE cxx_std_17)
target_compile_definitions(bividi-kimera-link-probe PRIVATE
    BIVIDI_KIMERA_VIO_PINNED_REVISION="${BIVIDI_KIMERA_VIO_PINNED_REVISION}"
    BIVIDI_KIMERA_VIO_TARGET_KIND="${BIVIDI_KIMERA_VIO_TARGET_KIND}"
)

enable_testing()
add_test(NAME bividi_kimera_external_link_probe COMMAND bividi-kimera-link-probe)

message(STATUS
    "Bividi Kimera external link probe: ${BIVIDI_KIMERA_VIO_TARGET} (${BIVIDI_KIMERA_VIO_TARGET_KIND})")
