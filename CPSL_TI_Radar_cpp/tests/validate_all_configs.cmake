# test_validate_all_configs (directive core-10): run the driver's --validate
# path over every tracked system config, and check the two fixed outcomes:
#   - every config/system/*.json exits 0 (schema v2, board descriptor, radar cfg
#     cross-checks, frame shape)
#   - an IWR1843 config lists calibData as skipped (cfg_dialect.skip_commands)
#   - a v1 file exits non-zero and names the migration script
# Invoked by ctest with -DDRIVER=<binary> -DCONFIG_DIR=<config> -DV1_FIXTURE=<v1 .json>.

file(GLOB configs "${CONFIG_DIR}/system/*.json")
list(LENGTH configs n)
if(n LESS 39)
  message(FATAL_ERROR "expected at least 39 tracked system configs, found ${n}")
endif()

set(failed 0)
foreach(cfg IN LISTS configs)
  execute_process(COMMAND "${DRIVER}" --validate "${cfg}"
                  RESULT_VARIABLE rc OUTPUT_VARIABLE out ERROR_VARIABLE err)
  get_filename_component(name "${cfg}" NAME)
  if(rc EQUAL 0)
    message(STATUS "ok    ${name}")
  else()
    message(STATUS "FAIL  ${name} (exit ${rc})\n${out}${err}")
    math(EXPR failed "${failed} + 1")
  endif()
endforeach()
if(failed GREATER 0)
  message(FATAL_ERROR "${failed} of ${n} system configs failed --validate")
endif()

execute_process(COMMAND "${DRIVER}" --validate "${CONFIG_DIR}/system/front_radar_IWR1843_stress_test_baseline.json"
                RESULT_VARIABLE rc OUTPUT_VARIABLE out ERROR_VARIABLE err)
if(NOT rc EQUAL 0 OR NOT out MATCHES "skipped: +calibData 0 0 0 \\(board skip_commands\\)")
  message(FATAL_ERROR "IWR1843 --validate does not list calibData as skipped:\n${out}${err}")
endif()

execute_process(COMMAND "${DRIVER}" --validate "${V1_FIXTURE}"
                RESULT_VARIABLE rc OUTPUT_VARIABLE out ERROR_VARIABLE err)
if(rc EQUAL 0 OR NOT err MATCHES "tools/migrate_config_v1_to_v2.py")
  message(FATAL_ERROR "v1 file was not rejected with the migration hint (exit ${rc}):\n${out}${err}")
endif()

execute_process(COMMAND "${DRIVER}" RESULT_VARIABLE rc OUTPUT_VARIABLE out ERROR_VARIABLE err)
if(rc EQUAL 0 OR NOT err MATCHES "usage:")
  message(FATAL_ERROR "no-argument run did not print usage and fail (exit ${rc})")
endif()

message(STATUS "${n} configs validated; calibData skip, v1 rejection and usage checked")
