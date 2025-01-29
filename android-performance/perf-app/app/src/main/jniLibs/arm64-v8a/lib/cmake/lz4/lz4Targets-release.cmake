#----------------------------------------------------------------
# Generated CMake target import file for configuration "Release".
#----------------------------------------------------------------

# Commands may need to know the format version.
set(CMAKE_IMPORT_FILE_VERSION 1)

# Import target "LZ4::lz4_shared" for configuration "Release"
set_property(TARGET LZ4::lz4_shared APPEND PROPERTY IMPORTED_CONFIGURATIONS RELEASE)
set_target_properties(LZ4::lz4_shared PROPERTIES
  IMPORTED_LOCATION_RELEASE "/data/data/com.termux/files/usr/lib/liblz4.so"
  IMPORTED_SONAME_RELEASE "liblz4.so"
  )

list(APPEND _cmake_import_check_targets LZ4::lz4_shared )
list(APPEND _cmake_import_check_files_for_LZ4::lz4_shared "/data/data/com.termux/files/usr/lib/liblz4.so" )

# Commands beyond this point should not need to know the version.
set(CMAKE_IMPORT_FILE_VERSION)
