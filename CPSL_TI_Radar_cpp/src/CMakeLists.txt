
#add subdirectories
add_subdirectory(utilities) #must be done first
add_subdirectory(CLIController)
add_subdirectory(DCA1000)

#if new libraries are created in this folder, declare them here

#link libraries

#link directories as needed
target_include_directories(CLIController PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/utilities)
target_include_directories(DCA1000Handler PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/utilities)