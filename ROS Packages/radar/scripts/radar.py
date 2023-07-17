#!/usr/bin/env python3

#ROS modules
import rospy
from sensor_msgs.msg import PointCloud2, PointField
import std_msgs.msg

#other modules
import numpy as np
from multiprocessing.connection import Client




def publish_point_cloud():
    """Initializes a ROS node to connect to the Radar streamer and publish the
      data in a ROS format
    """
    # Initialize ROS node
    rospy.init_node('radar', anonymous=True)

    # Create publisher for point cloud data
    pub = rospy.Publisher('radar_point_cloud', PointCloud2, queue_size=20)

    rospy.loginfo("Waiting to connect to Listener")
    address = ('localhost', 6000)     # family is deduced to be 'AF_INET'
    authkey_str = "TLV_client"
    conn = Client(address, authkey=authkey_str.encode())

    rospy.loginfo("Connected to Listener")

    while not rospy.is_shutdown():

        try:
            
            radar_point_cloud_xyz = conn.recv() #gives np.array(dtype=np.float32)

            # Create header for point cloud message
            header = std_msgs.msg.Header()
            header.stamp = rospy.Time.now()
            header.frame_id = 'Radar'

            # Create fields for point cloud message
            fields = [PointField('x', 0, PointField.FLOAT32, 1),
                    PointField('y', 4, PointField.FLOAT32, 1),
                    PointField('z', 8, PointField.FLOAT32, 1),
                    PointField('vel', 12, PointField.FLOAT32, 1),
                    PointField('rng', 16, PointField.FLOAT32, 1),
                    PointField('intensity', 20, PointField.FLOAT32, 1)]

            # Convert numpy array to string of bytes
            data_str = radar_point_cloud_xyz.tobytes()

            # Create point cloud message
            msg = PointCloud2()
            msg.header = header
            msg.height = 1
            msg.width = radar_point_cloud_xyz.shape[0]
            msg.fields = fields
            msg.is_bigendian = False
            msg.point_step = 24
            msg.row_step = len(data_str)
            msg.data = data_str

            # Publish point cloud message
            pub.publish(msg)
        except EOFError:
            rospy.loginfo("Listener connection was closed by Radar")
            break

if __name__ == '__main__':
    try:
        publish_point_cloud()
    except rospy.ROSInterruptException:
        pass

