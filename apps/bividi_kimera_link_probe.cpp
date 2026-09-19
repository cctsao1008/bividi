#include <kimera-vio/common/vio_types.h>
#include <kimera-vio/pipeline/Pipeline-definitions.h>

#include <cstdint>
#include <iostream>
#include <type_traits>

#ifndef BIVIDI_KIMERA_VIO_PINNED_REVISION
#error "BIVIDI_KIMERA_VIO_PINNED_REVISION must be supplied by the Bividi CMake gate"
#endif
#ifndef BIVIDI_KIMERA_VIO_TARGET_KIND
#error "BIVIDI_KIMERA_VIO_TARGET_KIND must be supplied by the Bividi CMake gate"
#endif

int main() {
    static_assert(std::is_same<VIO::Timestamp, std::int64_t>::value,
                  "Pinned Kimera VIO::Timestamp contract changed");

    // Empty path is the pinned upstream no-parse/default constructor path used
    // by its own VioParams tests. Construction forces a real link to Kimera.
    VIO::VioParams params("");
    (void)params;

    std::cout << "bividi Kimera external link probe: PASS\n"
              << "pinned_revision=" << BIVIDI_KIMERA_VIO_PINNED_REVISION << "\n"
              << "resolved_target_kind=" << BIVIDI_KIMERA_VIO_TARGET_KIND << "\n";
    return 0;
}
