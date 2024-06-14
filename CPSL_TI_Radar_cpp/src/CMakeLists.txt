
#add subdirectories
add_subdirectory(utilities) #must be done first
add_subdirectory(CLIController)

#if new libraries are created in this folder, declare them here

#link libraries

#link directories as needed
target_include_directories(CLIController PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/utilities)