
#add subdirectories
add_subdirectory(utilities) #must be done first
add_subdirectory(CLIController)
add_subdirectory(SerialStreamer)
add_subdirectory(DCA1000)
add_subdirectory(Runners)

#if new libraries are created in this folder, declare them here

#link libraries (if libraries are created in this folder)

#link directories as needed
target_include_directories(CLIController    PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/utilities)
target_include_directories(SerialStreamer   PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/utilities)
target_include_directories(DCA1000Handler   PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/utilities)
target_include_directories(DCA1000Runner    PUBLIC 
                                            ${CMAKE_CURRENT_SOURCE_DIR}/utilities
                                            ${CMAKE_CURRENT_SOURCE_DIR}/CLIController
                                            ${CMAKE_CURRENT_SOURCE_DIR}/SerialStreamer
                                            ${CMAKE_CURRENT_SOURCE_DIR}/DCA1000)
target_include_directories(Runner           PUBLIC 
                                            ${CMAKE_CURRENT_SOURCE_DIR}/utilities
                                            ${CMAKE_CURRENT_SOURCE_DIR}/CLIController
                                            ${CMAKE_CURRENT_SOURCE_DIR}/SerialStreamer
                                            ${CMAKE_CURRENT_SOURCE_DIR}/DCA1000)