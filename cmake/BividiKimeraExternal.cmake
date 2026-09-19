# External Kimera-VIO package gate for #142.
# Included by the explicit cmake/kimera-external/ probe project only.
set(BIVIDI_KIMERA_VIO_PINNED_REVISION "ce8c59b7b273ab5ac29db7e5572e1623760e19c7")

if(NOT DEFINED BIVIDI_KIMERA_VIO_REVISION OR BIVIDI_KIMERA_VIO_REVISION STREQUAL "")
    message(FATAL_ERROR
        "Kimera external probe requires BIVIDI_KIMERA_VIO_REVISION=${BIVIDI_KIMERA_VIO_PINNED_REVISION}")
endif()
if(NOT BIVIDI_KIMERA_VIO_REVISION STREQUAL BIVIDI_KIMERA_VIO_PINNED_REVISION)
    message(FATAL_ERROR
        "Kimera-VIO revision mismatch: expected ${BIVIDI_KIMERA_VIO_PINNED_REVISION}, got ${BIVIDI_KIMERA_VIO_REVISION}")
endif()

find_package(kimera_vio CONFIG REQUIRED)

# Pinned upstream exposes a namespaced alias in its build tree, but its install
# export is unnamespaced. Accept exactly those two surfaces and nothing else.
if(TARGET kimera_vio::kimera_vio)
    set(BIVIDI_KIMERA_VIO_TARGET kimera_vio::kimera_vio)
    set(BIVIDI_KIMERA_VIO_TARGET_KIND "build-tree-alias")
elseif(TARGET kimera_vio)
    set(BIVIDI_KIMERA_VIO_TARGET kimera_vio)
    set(BIVIDI_KIMERA_VIO_TARGET_KIND "installed-export")
else()
    message(FATAL_ERROR
        "kimera_vio package found, but neither kimera_vio::kimera_vio nor kimera_vio target exists")
endif()
