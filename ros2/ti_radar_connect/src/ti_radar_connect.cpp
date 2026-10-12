#include <string>
#include <cstdlib>
#include <csignal>

#include "rclcpp/rclcpp.hpp"
#include "TIRadarConnectNode.hpp"


int main(int argc, char * argv[])
{
    rclcpp::init(argc,argv);
    int exit_code = 1;
    {
        auto node = std::make_shared<TIRadarConnectNode>();
        // Fail loud: a radar that could not be opened/configured exits non-zero
        // (the node has already logged why); it never idles as a silent node.
        // run() is the blocking capture loop; it returns once rclcpp::ok() goes
        // false (SIGINT) or the radar fails, and its value is the exit code.
        if(node->ok()){
            exit_code = node->run();
        }
    }
    if(rclcpp::ok()){
        rclcpp::shutdown();
    }
    return exit_code;
}
