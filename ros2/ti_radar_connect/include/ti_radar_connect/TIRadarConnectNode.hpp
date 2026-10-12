#ifndef TI_RADAR_CONNECT_NODE
#define TI_RADAR_CONNECT_NODE

#include <chrono>
#include <complex>
#include <cstdint>
#include <cstdlib>
#include <endian.h>
#include <memory>
#include <string>
#include <vector>

#include "rclcpp/rclcpp.hpp"
#include "sensor_msgs/msg/point_cloud2.hpp"
#include "sensor_msgs/point_cloud2_iterator.hpp"
#include "std_msgs/msg/string.hpp"
#include "raw_radar_msgs/msg/multi_array_dimension.hpp"
#include "raw_radar_msgs/msg/adc_data_cube.hpp"
#include "raw_radar_msgs/msg/adc_chirp_meta.hpp"

// CPSL_TI_Radar v2 public API (Radar, RadarConfig, Status, AdcFrame, PointCloud)
#include "Radar.hpp"

/**
 * Publishes a TI radar through the CPSL_TI_Radar v2 driver.
 *
 * Construction only declares parameters and opens/configures the radar;
 * check ok() afterwards. run() is the capture loop and returns a process exit
 * code (0 = clean stop on shutdown, non-zero = the radar failed).
 */
class TIRadarConnectNode : public rclcpp::Node
{
//functions
public:
    TIRadarConnectNode();
    ~TIRadarConnectNode();

    // true if the radar was opened, configured and is ready to start
    bool ok(void) const { return startup_ok_; }

    // start the radar and capture until shutdown or failure; returns an exit code
    int run(void);
private:
    //publishing data
    void pub_radar_config_path(void);

    //time handling
    rclcpp::Time to_ros_time(std::chrono::steady_clock::time_point t) const;

    //generating messages
    sensor_msgs::msg::PointCloud2 get_pointcloud2_msg(
        const std::vector<cpsl::radar::Point> &detected_points,
        rclcpp::Time timestamp);

    raw_radar_msgs::msg::ADCDataCube get_AdcDataCube_msg(
        const cpsl::radar::AdcFrame & frame,
        rclcpp::Time timestamp
    );
    raw_radar_msgs::msg::ADCChirpMeta get_AdcChirpMeta_msg(
        const cpsl::radar::AdcFrame & frame,
        rclcpp::Time timestamp
    );
    void save_adc_cube_to_msg(
        const std::vector<std::vector<std::vector<std::complex<std::int16_t>>>> & adc_cube,
        raw_radar_msgs::msg::ADCDataCube & msg
    );

    void log_counters(bool final_report);
//variables
private:

    //config paths
    std::string config_path;
    std::string frame_id;
    double stamp_delay_sec;
    rclcpp::Duration stamp_delay;
    std::string radar_config_path;

    //the driver
    std::unique_ptr<cpsl::radar::Radar> radar_;
    bool startup_ok_;
    bool pointcloud_enabled_;
    bool adc_enabled_;

    //offset (ns) added to a steady_clock time point to get ROS time; taken once at start
    int64_t steady_to_ros_offset_ns_;

    //publishers
    rclcpp::Publisher<std_msgs::msg::String>::SharedPtr radar_config_path_pub_;
    rclcpp::Publisher<sensor_msgs::msg::PointCloud2>::SharedPtr detected_points_pub_;
    rclcpp::Publisher<raw_radar_msgs::msg::ADCDataCube>::SharedPtr adc_data_cube_pub_;
    bool publish_chirp_meta_;   //param publish_chirp_meta is true AND the stream carries meta
    rclcpp::Publisher<raw_radar_msgs::msg::ADCChirpMeta>::SharedPtr adc_meta_pub_;
};

#endif
