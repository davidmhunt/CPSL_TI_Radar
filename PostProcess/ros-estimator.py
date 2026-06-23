import rclpy
from rclpy.node import Node
from std_msgs.msg import Header, MultiArrayDimension
from radar_msgs.msg import ADCDataCube  
import numpy as np
from multiprocessing.connection import Client
from multiprocessing import connection
import json
import os
from scipy.signal import find_peaks
from sklearn.cluster import DBSCAN
from decimal import Decimal

timestamps_0 = []
timestamps_1 = []

def read_config(config_path):
    config = {'Profile 0': {}, 'Profile 1': {}}
    current_profile = None

    with open(config_path, 'r') as f:
        lines = f.readlines()
        for line in lines:
            line = line.strip()
            if line.startswith('%'):
                current_profile = line[1:]
            elif line and current_profile:
                parts = line.split()
                key = parts[0]
                values = [float(v) if '.' in v else int(v) for v in parts[1:]]
                config[current_profile][key] = values

    return config

def cfar_ca1d(magnitude, num_train, num_guard, rate_fa):
    n = len(magnitude)
    alpha = num_train * (rate_fa ** (-1 / num_train) - 1)
    peak_idx = []

    for i in range(num_guard, num_train + num_guard):
        lagging_train = magnitude[i + num_guard + 1:i + num_guard + 1 + num_train]
        noise_level = np.sum(lagging_train) / num_train
        threshold = alpha * noise_level
        if magnitude[i] > threshold:
            peak_idx.append(i)

    for i in range(num_train + num_guard, n - num_train - num_guard):
        leading_train = magnitude[i - num_train - num_guard:i - num_guard]
        lagging_train = magnitude[i + num_guard + 1:i + num_guard + 1 + num_train]
        noise_level = (np.sum(leading_train) + np.sum(lagging_train)) / (2 * num_train)
        threshold = alpha * noise_level
        if magnitude[i] > threshold:
            peak_idx.append(i)

    for i in range(n - num_train - num_guard, n - num_guard):
        leading_train = magnitude[i - num_train - num_guard:i - num_guard]
        noise_level = np.sum(leading_train) / num_train
        threshold = alpha * noise_level
        if magnitude[i] > threshold:
            peak_idx.append(i)

    return np.array(peak_idx)

def analyze_periods(timestamps):
    timestamps = np.array([Decimal(str(t[0])) for t in timestamps])
    periods = np.diff(timestamps) 
    periods_reshaped = periods.reshape(-1, 1)
    dbscan = DBSCAN(eps=0.005, min_samples=5).fit(periods_reshaped)
    labels = dbscan.labels_

    unique_labels, counts = np.unique(labels, return_counts=True)
    main_cluster_label = unique_labels[np.argmax(counts)]

    filtered_periods = periods[labels == main_cluster_label]
    outliers = periods[labels != main_cluster_label]

    unique_periods, counts = np.unique(filtered_periods, return_counts=True)

    return unique_periods, counts, outliers

def analyze_slopes(timestamps):
    times = np.array([Decimal(str(t[0])) for t in timestamps])
    freqs = np.array([Decimal(str(t[1])) for t in timestamps])
    
    slopes = np.diff(freqs) / np.diff(times)
    
    slopes_reshaped = slopes.reshape(-1, 1)
    dbscan = DBSCAN(eps=0.01, min_samples=5).fit(slopes_reshaped)
    labels = dbscan.labels_

    unique_labels, counts = np.unique(labels, return_counts=True)
    main_cluster_label = unique_labels[np.argmax(counts)]

    filtered_slopes = slopes[labels == main_cluster_label]
    outliers = slopes[labels != main_cluster_label]

    unique_slopes, counts = np.unique(filtered_slopes, return_counts=True)

    return unique_slopes, counts, outliers

def analyze_interference_batches(timestamps):
    batches = []
    batch_start_indices = [0]
    
    for i in range(1, len(timestamps)):
        if Decimal(str(timestamps[i][0])) - Decimal(str(timestamps[i-1][0])) > Decimal('50'):
            batch_start_indices.append(i)

    batch_start_times = [Decimal(str(timestamps[i][0])) for i in batch_start_indices]
    batch_periods = np.array([float(batch_start_times[i+1] - batch_start_times[i]) for i in range(len(batch_start_times) - 1)], dtype=np.float64)
    batch_periods = np.diff(batch_start_times)

    if len(batch_periods) == 0:
        return [], []

    batch_periods_reshaped = batch_periods.reshape(-1, 1)
    dbscan = DBSCAN(eps=0.1, min_samples=5).fit(batch_periods_reshaped)
    labels = dbscan.labels_

    unique_labels, counts = np.unique(labels, return_counts=True)
    main_cluster_label = unique_labels[np.argmax(counts)]

    filtered_batch_periods = batch_periods[labels == main_cluster_label]
    outliers = batch_periods[labels != main_cluster_label]

    unique_batch_periods, counts = np.unique(filtered_batch_periods, return_counts=True)

    return unique_batch_periods, counts, outliers

class ADCProcessor(Node):
    def __init__(self, config_path):
        super().__init__('adc_processor')

        self.subscription = self.create_subscription(
            ADCDataCube,
            'radar_{0}/ADCDataCube/Array',
            self.listener_callback,
            10)
        
        config = read_config(config_path)
        self.config_0 = config['Profile 0']
        self.config_1 = config['Profile 1']
        self.frame_index = 0  

    def listener_callback(self, msg):
        global timestamps_0, timestamps_1

        real_data = np.array(msg.real_data, dtype=np.int16)
        imag_data = np.array(msg.imag_data, dtype=np.int16)
        adc_data = real_data + 1j * imag_data
        adc_data = adc_data.reshape(2, 4, 256, 128)

        num_samples_0 = int(self.config_0['profileCfg'][9])
        num_samples_1 = int(self.config_1['profileCfg'][9])
        num_chirps_0 = int(self.config_0['frameCfg'][2])
        num_chirps_1 = int(self.config_1['frameCfg'][2])
        num_rx = 4  
        rx_channel = 0

        sample_rate_0 = float(self.config_0['profileCfg'][10])
        sample_rate_1 = float(self.config_1['profileCfg'][10]) 
        frame_periodicity_0 = int(self.config_0['frameCfg'][4]) 
        frame_periodicity_1 = int(self.config_1['frameCfg'][4])
        idle_time_0 = float(self.config_0['profileCfg'][2]) * 1e-3
        idle_time_1 = float(self.config_1['profileCfg'][2]) * 1e-3
        ramp_time_0 = float(self.config_0['profileCfg'][4]) * 1e-3
        ramp_time_1 = float(self.config_1['profileCfg'][4]) * 1e-3
        adc_start_time_0 = float(self.config_0['profileCfg'][3]) * 1e-3
        adc_start_time_1 = float(self.config_1['profileCfg'][3]) * 1e-3

        for chirp_idx in range(num_chirps_0):
            chirp_data_0 = adc_data[0][rx_channel, :, chirp_idx]
            chirp_data_1 = adc_data[1][rx_channel, :, chirp_idx]

            time_per_sample_0 = 1 / sample_rate_0
            time_per_sample_1 = 1 / sample_rate_1
            start_time_0 = self.frame_index * frame_periodicity_0 + (2 * chirp_idx) * (idle_time_0 + ramp_time_0) + (idle_time_0 + adc_start_time_0)
            start_time_1 = self.frame_index * frame_periodicity_1 + (2 * chirp_idx + 1) * (idle_time_1 + ramp_time_1) + (idle_time_1 + adc_start_time_1)
            time_indices_0 = start_time_0 + np.arange(num_samples_0) * time_per_sample_0
            time_indices_1 = start_time_1 + np.arange(num_samples_1) * time_per_sample_1

            complex_magnitude_0 = np.abs(chirp_data_0)
            complex_magnitude_1 = np.abs(chirp_data_1)
            
            num_train = 10  
            num_guard = 2   
            rate_fa = 1e-2  
            
            peak_idx_0 = cfar_ca1d(complex_magnitude_0, num_train, num_guard, rate_fa)
            peak_idx_1 = cfar_ca1d(complex_magnitude_1, num_train, num_guard, rate_fa)

            for idx in peak_idx_0:
                if not any(np.isclose(time_indices_0[idx], t[0]) for t in timestamps_0):
                    timestamps_0.append((time_indices_0[idx], float(self.config_0['profileCfg'][1])))

            for idx in peak_idx_1:
                if not any(np.isclose(time_indices_1[idx], t[0]) for t in timestamps_1):
                    timestamps_1.append((time_indices_1[idx], float(self.config_1['profileCfg'][1])))

        if len(timestamps_0) > 1:
            timestamps_0.sort(key=lambda x: x[0])
            unique_periods_0, counts_0, outliers_0 = analyze_periods(timestamps_0)
            unique_batch_periods_0, batch_counts_0, batch_outliers_0 = analyze_interference_batches(timestamps_0)
            self.get_logger().info(f"Profile 0 - Timestamps: {[float(t[0]) for t in timestamps_0]}")
            self.get_logger().info(f"Profile 0 - Unique Periods: {[float(p) for p in unique_periods_0]}, Counts: {counts_0}")
            self.get_logger().info(f"Profile 0 - Batch Periods: {[float(bp) for bp in unique_batch_periods_0]}, Counts: {batch_counts_0}")

        if len(timestamps_1) > 1:
            timestamps_1.sort(key=lambda x: x[0])
            unique_periods_1, counts_1, outliers_1 = analyze_periods(timestamps_1)
            unique_batch_periods_1, batch_counts_1, batch_outliers_1 = analyze_interference_batches(timestamps_1)
            self.get_logger().info(f"Profile 1 - Timestamps: {[float(t[0]) for t in timestamps_1]}")
            self.get_logger().info(f"Profile 1 - Unique Periods: {[float(p) for p in unique_periods_1]}, Counts: {counts_1}")
            self.get_logger().info(f"Profile 1 - Batch Periods: {[float(bp) for bp in unique_batch_periods_1]}, Counts: {batch_counts_1}")

            timestamps = timestamps_0 + timestamps_1
            timestamps.sort(key=lambda x: x[0])
            unique_slopes, slope_counts, slope_outliers = analyze_slopes(timestamps)

            self.get_logger().info(f"Slopes: {unique_slopes}, Counts: {slope_counts}")

            average_slope = np.average(unique_slopes, weights=slope_counts)
            self.get_logger().info(f"Weighted Average Slope: {average_slope}")

            if len(unique_periods_0) > 0:
                average_period_0 = np.average(unique_periods_0, weights=counts_0)
                self.get_logger().info(f"Weighted Average Period (Profile 0): {average_period_0}")

            if len(unique_periods_1) > 0:
                average_period_1 = np.average(unique_periods_1, weights=counts_1)
                self.get_logger().info(f"Weighted Average Period (Profile 1): {average_period_1}")

            if len(unique_batch_periods_0) > 0:
                average_batch_period_0 = np.average(unique_batch_periods_0, weights=batch_counts_0)
                self.get_logger().info(f"Weighted Average Batch Period (Profile 0): {average_batch_period_0}")

            if len(unique_batch_periods_1) > 0:
                average_batch_period_1 = np.average(unique_batch_periods_1, weights=batch_counts_1)
                self.get_logger().info(f"Weighted Average Batch Period (Profile 1): {average_batch_period_1}")

        self.frame_index += 1

def main(args=None):
    rclpy.init(args=args)
    config_path = "/Users/edwardju/Downloads/IWR 1443 Profile 1.cfg"  
    node = ADCProcessor(config_path)
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
