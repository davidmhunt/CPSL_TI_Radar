#!/usr/bin/env python

#ROS modules
import rospy
from sensor_msgs.msg import PointCloud2, PointField
import std_msgs.msg

#coordinate transformations
import tf
import tf2_ros
import tf_conversions
import geometry_msgs.msg

#other modules
import numpy as np
from multiprocessing.connection import Client

def init_radar_static_frame():

    #create a ROS node
    rospy.init_node('radar_reference_frame',anonymous=True)

    #create a static transform broadcaster
    broadcaster = tf2_ros.StaticTransformBroadcaster()
    static_transformStamped = geometry_msgs.msg.TransformStamped()

    #create the header
    static_transformStamped.header.stamp = rospy.Time.now()
    #TODO: Change frame_id to be desired parent frame id
    static_transformStamped.header.frame_id = "vicon/drone1/drone1" #"turtle1"
    static_transformStamped.child_frame_id = "Radar"

    #specify translation transformation (m)
    #TODO: update translation in x to be correct value for drone
    static_transformStamped.transform.translation.x = 0.2
    static_transformStamped.transform.translation.y = 0.0
    static_transformStamped.transform.translation.z = 0.0

    #specfiy rotation transformations (radians)
    q = tf_conversions.transformations.quaternion_from_euler(0,0,np.pi/2)
    static_transformStamped.transform.rotation.x = q[0]
    static_transformStamped.transform.rotation.y = q[1]
    static_transformStamped.transform.rotation.z = q[2]
    static_transformStamped.transform.rotation.w = q[3]

    #broadcast the node
    broadcaster.sendTransform(static_transformStamped)
    rospy.spin()

if __name__ == '__main__':
    try:
        init_radar_static_frame()
    except rospy.ROSInterruptException:
        pass
