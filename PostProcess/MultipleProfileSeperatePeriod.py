import numpy as np
import scipy.fft as fft
from scipy.signal import find_peaks
import matplotlib.pyplot as plt
from matplotlib.widgets import Button
from mpl_toolkits.mplot3d import Axes3D
import mplcursors
from MMWaveDevice import MMWaveDevice
from sklearn.cluster import DBSCAN
import matplotlib.ticker as ticker

running = True
running_chirp = True

timestamps_0 = []
timestamps_1 = []

prev_interference_times_0 = []
prev_bounds_0 = []

prev_interference_times_1 = []
prev_bounds_1 = []

def read_adc_data(adc_data_bin_file, mmwave_device_0, mmwave_device_1):
    num_samples_0 = mmwave_device_0.num_sample_per_chirp
    num_samples_1 = mmwave_device_1.num_sample_per_chirp
    num_chirps_0 = mmwave_device_0.num_chirp_per_frame
    num_chirps_1 = mmwave_device_1.num_chirp_per_frame
    num_frames = mmwave_device_0.num_frame
    num_rx = mmwave_device_0.num_rx_chnl
    num_lanes = 4

    adc_data = np.fromfile(adc_data_bin_file, dtype=np.int16)
    expected_size = (num_samples_0 * num_chirps_0 + num_samples_1 * num_chirps_1) * num_frames * num_rx * 2
    if adc_data.size != expected_size:
        raise ValueError(f"Size of the adc data ({adc_data.size}) does not match the expected size ({expected_size})")

    if mmwave_device_0.adc_bits != 16:
        l_max = 2**(mmwave_device_0.adc_bits - 1) - 1
        adc_data[adc_data > l_max] -= 2**mmwave_device_0.adc_bits

    if mmwave_device_0.is_iq_swap:
        adc_data = adc_data.reshape(-1, num_lanes).T
    else:
        adc_data = adc_data.reshape(-1, num_lanes * 2).T
        adc_data = adc_data[:num_lanes] + 1j * adc_data[num_lanes:]

    adc_data = adc_data.T.flatten()

    adc_data_0 = adc_data[0::2].reshape((num_frames, num_chirps_0, num_samples_0, num_rx)).transpose(2, 1, 0, 3)
    adc_data_1 = adc_data[1::2].reshape((num_frames, num_chirps_1, num_samples_1, num_rx)).transpose(2, 1, 0, 3)

    return adc_data_0, adc_data_1


def range_fft(adc_data, range_data, num_samples, num_chirps, num_rx, win_hann, dbfs_coeff):
    for chirp in range(num_chirps):
        for rx in range(num_rx):
            adc_data_segment = adc_data[:, chirp, rx]
            windowed_data = win_hann * adc_data_segment
            fft_data = 20 * np.log10(np.abs(fft.fft(windowed_data)) + 1e-6)
            range_data[:, chirp, rx] = fft_data + dbfs_coeff

def compute_range_doppler(adc_data, num_samples, num_chirps, num_frames):
    fft_range_doppler_cube = np.zeros((num_samples, num_chirps, num_frames), dtype=np.complex128)
    for frame_index in range(num_frames):
        fft_range_doppler_cube[:, :, frame_index] = fft.fftshift(fft.fft(adc_data[:, :, frame_index, 0], axis=1), axes=1)

    for chirp_index in range(num_chirps):
        fft_range_doppler_cube[:, chirp_index, :] = fft.fft(fft_range_doppler_cube[:, chirp_index, :], axis=0)

    return 20 * np.log10(np.abs(fft_range_doppler_cube))

def plot_range_doppler(ax, range_doppler_data, v_max, v_res, num_samples, num_chirps, range_res, desired_frame):
    velocities = np.linspace(-v_max, v_max, num_chirps)
    ranges = np.arange(num_samples) * range_res
    
    frame_data = range_doppler_data[:, :, desired_frame] 

    ax.clear()
    ax.imshow(frame_data, aspect='auto', extent=[velocities.min(), velocities.max(), ranges.max(), ranges.min()], cmap='viridis')
    title_str = f'Range-Doppler FFT Plot - Magnitudes for frame: {desired_frame}'
    ax.set_title(title_str)
    ax.set_xlabel('Velocity (m/s)')
    ax.set_ylabel('Range (m)')

def on_key_press(event):
    if event.key == 'q':
        plt.close(event.canvas.figure)

def plot_adc_data(ax, line_real, line_imag, adc_data, num_samples, num_chirps, desired_frame, desired_chirp, rx_channel, frame_periodicity, sample_rate, idle_time, adc_start_time, ramp_time, freq, profile_index):
    global timestamps_0, timestamps_1
    data = adc_data[:, desired_chirp, desired_frame, rx_channel]
    t = np.linspace(0, num_samples-1, num_samples)

    time_per_sample = 1 / sample_rate
    time_indices = desired_frame * frame_periodicity + (2 * desired_chirp + profile_index) * (idle_time + ramp_time) + (idle_time + adc_start_time) + t * time_per_sample

    complex_magnitude = np.abs(data)
    threshold = 50 if freq > 77 else 50

    if np.any(complex_magnitude > threshold):
        if profile_index == 0:
            timestamps_0.append((time_indices[np.argmax(complex_magnitude > threshold)], freq))
        else:
            timestamps_1.append((time_indices[np.argmax(complex_magnitude > threshold)], freq))

    line_real.set_xdata(t)
    line_imag.set_xdata(t)
    line_real.set_ydata(data.real)
    line_imag.set_ydata(data.imag)

    ax.set_title(f'ADC data for Frame: {desired_frame}, Chirp: {desired_chirp}, Profile: {profile_index}')  
    ax.relim()
    ax.autoscale_view()


def plot_2d_fft_3d(ax, adc_data, num_samples, num_chirps, rx_channel, desired_frame, range_res):
    frame_data = adc_data[:, :, desired_frame-1, rx_channel]
    frame_data = np.reshape(frame_data, (num_samples, num_chirps))
    fft_2d_range = np.zeros((num_samples, num_chirps))
    for chirp in range(num_chirps):
        frame_data_chirp = frame_data[:, chirp]
        fft_2d_range[:, chirp] = 20 * np.log10(np.abs(fft.fft(frame_data_chirp)) + 1e-6)
    x_vals = np.arange(1, num_chirps + 1)
    y_vals = np.arange(num_samples) * range_res

    X, Y = np.meshgrid(x_vals, y_vals)

    ax.clear()
    ax.plot_surface(X, Y, fft_2d_range, cmap='viridis')
    title_str = f'2D Range FFT for frame: {desired_frame}'
    ax.set_title(title_str)
    ax.set_xlabel('Chirp')
    ax.set_ylabel('Range (m)')
    ax.set_zlabel('Magnitude (dB)')

def plot_2d_fft_image(ax, adc_data, num_samples, num_chirps, num_frames, rx_channel, desired_frame, range_res):
    frame_data = adc_data[:, :, desired_frame-1, rx_channel]
    frame_data = np.reshape(frame_data, (num_samples, num_chirps))
    fft_2d_range = np.zeros((num_samples, num_chirps))
    for chirp in range(num_chirps):
        frame_data_chirp = frame_data[:, chirp]
        fft_2d_range[:, chirp] = 20 * np.log10(np.abs(fft.fft(frame_data_chirp)))
    x_vals = np.arange(1, num_chirps + 1)
    y_vals = np.arange(num_samples) * range_res

    ax.clear()
    im = ax.imshow(fft_2d_range, aspect='auto', extent=[x_vals.min(), x_vals.max(), y_vals.max(), y_vals.min()], cmap='viridis')

    title_str = f'2D Range FFT for frame: {desired_frame}'
    ax.set_title(title_str)
    ax.set_xlabel('Chirp')
    ax.set_ylabel('Range(m)')

    cursor = mplcursors.cursor(im, hover=True)

    @cursor.connect("add")
    def on_add(sel):
        x, y = sel.target
        sel.annotation.set(text=f'Chirp: {x:.2f}, Range: {y:.2f} m, Value: {fft_2d_range[int(y/range_res), int(x)]:.2f} dB')

def toggle_running(event):
    global running
    running = not running

def toggle_running_chirp(event):
    global running_chirp
    running_chirp = not running_chirp

def analyze_periods(timestamps):
    timestamps = np.array([t[0] for t in timestamps]) 
    periods = np.diff(timestamps) 

    periods = np.round(periods, 4)

    periods_reshaped = periods.reshape(-1, 1)
    dbscan = DBSCAN(eps=0.01, min_samples=5).fit(periods_reshaped)
    labels = dbscan.labels_

    unique_labels, counts = np.unique(labels, return_counts=True)
    main_cluster_label = unique_labels[np.argmax(counts)]

    filtered_periods = periods[labels == main_cluster_label]
    outliers = periods[labels != main_cluster_label]
    print("Outliers:", outliers)

    unique_periods, counts = np.unique(filtered_periods, return_counts=True)

    return unique_periods, counts


def predict_next_interference(timestamps, unique_periods, counts, frame_periodicity, idle_time, adc_start_time, profile):
    if len(unique_periods) > 0 and counts.max() >= 3:
        mean_period = np.mean(unique_periods)
        last_timestamp = timestamps[-1][0]
        next_interference_time = last_timestamp + mean_period
        lower_bound = last_timestamp + mean_period - 0.25
        upper_bound = last_timestamp + mean_period + 0.25

        n = int(next_interference_time // frame_periodicity)
        start_time = frame_periodicity * n + idle_time + adc_start_time
        end_time = frame_periodicity * (n + 1)

        if start_time <= next_interference_time <= end_time:
            return next_interference_time, lower_bound, upper_bound, profile

    return None, None, None, None


def plot_periods(ax, unique_periods, counts):
    ax.clear()
    if len(unique_periods) > 0:
        if unique_periods.max() == unique_periods.min():
            ax.hist(unique_periods, bins=20, weights=counts, edgecolor='black', align='mid')
        else:
            bin_edges = np.linspace(unique_periods.min(), unique_periods.max(), len(unique_periods) + 1)
            ax.hist(unique_periods, bins=bin_edges, weights=counts, edgecolor='black', align='mid')
    else:
        ax.hist(unique_periods, bins=20, weights=counts, edgecolor='black', align='mid')

    ax.set_title('Detected Periods')
    ax.set_xlabel('Period (ms)')
    ax.set_ylabel('Frequency')

    ax.xaxis.set_major_formatter(ticker.ScalarFormatter())
    ax.xaxis.get_major_formatter().set_useOffset(False)

    plt.draw()

def plot_prediction(ax, next_interference_time, lower_bound, upper_bound, timestamps, frame_periodicity, idle_time, adc_start_time, unique_periods, counts, profile):
    global prev_interference_times_0, prev_bounds_0, prev_interference_times_1, prev_bounds_1
    ax.clear()

    times_0 = [t[0] for t in timestamps_0]
    freqs_0 = [t[1] for t in timestamps_0]
    times_1 = [t[0] for t in timestamps_1]
    freqs_1 = [t[1] for t in timestamps_1]

    ax.plot(times_0, freqs_0, 'o', label='Profile 0 Interference Times', color='blue')

    ax.plot(times_1, freqs_1, 'o', label='Profile 1 Interference Times', color='orange')


    for interference_time, bounds in zip(prev_interference_times_0, prev_bounds_0):
        if interference_time is not None:
            ax.axvline(interference_time, ymin=0, ymax=0.5, color='g', linestyle='--') 
            if bounds:
                good_range_start = max(bounds[0], frame_periodicity * (interference_time // frame_periodicity) + idle_time + adc_start_time)
                good_range_end = min(bounds[1], frame_periodicity * (interference_time // frame_periodicity + 1))
                if good_range_start < good_range_end:
                    ax.fill_betweenx([77.0, 78], good_range_start, good_range_end, color='g', alpha=0.3)

    for interference_time, bounds in zip(prev_interference_times_1, prev_bounds_1):
        if interference_time is not None:
            ax.axvline(interference_time, ymin=0.5, ymax=1.0, color='g', linestyle='--')
            if bounds:
                good_range_start = max(bounds[0], frame_periodicity * (interference_time // frame_periodicity) + idle_time + adc_start_time)
                good_range_end = min(bounds[1], frame_periodicity * (interference_time // frame_periodicity + 1))
                if good_range_start < good_range_end:
                    ax.fill_betweenx([78.5, 79.5], good_range_start, good_range_end, color='g', alpha=0.3)

    prev_interference_times = (prev_interference_times_0 + prev_interference_times_1)
    prev_interference_times.sort()

    print("next inter")
    print(next_interference_time)
    if next_interference_time is not None and (prev_interference_times == [] or next_interference_time >= prev_interference_times[-1] + idle_time * 100 + 0.5):
        if prev_interference_times_0 and prev_interference_times_1:
            print(next_interference_time - prev_interference_times[-1] - idle_time * 100)
            print(prev_interference_times)
        good_range_start = max(lower_bound, frame_periodicity * (next_interference_time // frame_periodicity) + idle_time + adc_start_time)
        good_range_end = min(upper_bound, frame_periodicity * (next_interference_time // frame_periodicity + 1))
        if good_range_start < good_range_end:
            if profile == 0:
                ax.axvline(next_interference_time, ymin=0, ymax=0.5, color='r', linestyle='--', label='Predicted Next Interference')
                ax.fill_betweenx([77.0, 78], good_range_start, good_range_end, color='r', alpha=0.3, label='Prediction Range')
                prev_interference_times_0.append(next_interference_time)
                prev_bounds_0.append((lower_bound, upper_bound))
            else:
                ax.axvline(next_interference_time, ymin=0.5, ymax=1.0, color='r', linestyle='--', label='Predicted Next Interference') 
                ax.fill_betweenx([78.5, 79.5], good_range_start, good_range_end, color='r', alpha=0.3, label='Prediction Range')
                prev_interference_times_1.append(next_interference_time)
                prev_bounds_1.append((lower_bound, upper_bound))

    if len(unique_periods) > 0 and counts.max() >= 3:
        mean_period = np.mean(unique_periods)
        window_size = mean_period * 20
    else:
        window_size = 10

    current_time = max(times_0 + times_1) if (times_0 + times_1) else 0
    ax.set_xlim([max(0, current_time - window_size), current_time + window_size / 10 + 1e-6])
    ax.set_ylim([76.5, 80.0])
    ax.set_title('Prediction of Next Interference')
    ax.set_xlabel('Time (10$^{-4}$ seconds)')
    ax.set_ylabel('Frequency (GHz)')
    ax.legend()
    plt.draw()


def main():
    adc_data_bin_file = '/Users/edwardju/Downloads/adc_data_RangeDopplerTest.bin'
    mmwave_setup_json_file = '/Users/edwardju/Downloads/RangeDopplerTest.mmwave.json'
    
    mmwave_device_profile_0 = MMWaveDevice(adc_data_bin_file, mmwave_setup_json_file, profile_id=0)
    mmwave_device_profile_0.print_device_configuration()
    
    mmwave_device_profile_1 = MMWaveDevice(adc_data_bin_file, mmwave_setup_json_file, profile_id=1)
    mmwave_device_profile_1.print_device_configuration()

    adc_data_profile_0, adc_data_profile_1 = read_adc_data(adc_data_bin_file, mmwave_device_profile_0, mmwave_device_profile_1)
    
    num_samples_0 = mmwave_device_profile_0.num_sample_per_chirp
    num_chirps_0 = mmwave_device_profile_0.num_chirp_per_frame
    num_frames_0 = mmwave_device_profile_0.num_frame
    num_rx_0 = mmwave_device_profile_0.num_rx_chnl
    win_hann_0 = mmwave_device_profile_0.win_hann
    dbfs_coeff_0 = mmwave_device_profile_0.dbfs_coeff
    range_res_0 = mmwave_device_profile_0.range_res
    frame_periodicity_0 = mmwave_device_profile_0.frame_periodicity 
    idle_time_0 = mmwave_device_profile_0.chirp_idle_time / 1000
    adc_start_time_0 = mmwave_device_profile_0.chirp_adc_start_time / 1000
    sample_rate_0 = mmwave_device_profile_0.adc_samp_rate * 1000
    ramp_time_0 = mmwave_device_profile_0.chirp_ramp_time / 1000
    freq_0 = mmwave_device_profile_0.freq / 1e9
    v_max_0 = mmwave_device_profile_0.v_max
    v_res_0 = mmwave_device_profile_0.v_res

    num_samples_1 = mmwave_device_profile_1.num_sample_per_chirp
    num_chirps_1 = mmwave_device_profile_1.num_chirp_per_frame
    num_frames_1 = mmwave_device_profile_1.num_frame
    num_rx_1 = mmwave_device_profile_1.num_rx_chnl
    win_hann_1 = mmwave_device_profile_1.win_hann
    dbfs_coeff_1 = mmwave_device_profile_1.dbfs_coeff
    range_res_1 = mmwave_device_profile_1.range_res
    frame_periodicity_1 = mmwave_device_profile_1.frame_periodicity 
    idle_time_1 = mmwave_device_profile_1.chirp_idle_time / 1000
    adc_start_time_1 = mmwave_device_profile_1.chirp_adc_start_time / 1000
    sample_rate_1 = mmwave_device_profile_1.adc_samp_rate * 1000
    ramp_time_1 = mmwave_device_profile_1.chirp_ramp_time / 1000
    freq_1 = mmwave_device_profile_1.freq / 1e9
    v_max_1 = mmwave_device_profile_1.v_max
    v_res_1 = mmwave_device_profile_1.v_res

    range_data_0 = np.zeros((num_samples_0, num_chirps_0, num_rx_0), dtype=np.float32)
    range_data_1 = np.zeros((num_samples_1, num_chirps_1, num_rx_1), dtype=np.float32)

    desired_frame = 1
    rx_channel = 0

    plt.ion()
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 12))
    
    line1, = ax1.plot(np.zeros(num_samples_0))
    ax1.set_title('Range FFT (Profile 0)')
    ax1.set_xlabel('Range (m)')
    ax1.set_ylabel('Magnitude (dB)')

    line_real, = ax2.plot(np.zeros(num_samples_0), label='real')
    line_imag, = ax2.plot(np.zeros(num_samples_0), label='imaginary')
    ax2.set_xlabel('Sample index')
    ax2.set_ylabel('Amplitude')
    ax2.legend()

    fig.canvas.mpl_connect('key_press_event', on_key_press)

    fig2 = plt.figure(figsize=(12, 6))
    ax3 = fig2.add_subplot(121, projection='3d')
    ax4 = fig2.add_subplot(122)

    fig4, ax6 = plt.subplots(figsize=(6, 6))

    fig_chirp, ax_chirp = plt.subplots(figsize=(12, 6))
    line_real_chirp, = ax_chirp.plot(np.zeros(num_samples_0), label='real')
    line_imag_chirp, = ax_chirp.plot(np.zeros(num_samples_0), label='imaginary')
    ax_chirp.set_xlabel('Sample index')
    ax_chirp.set_ylabel('Amplitude')
    ax_chirp.legend()

    fig_periods, ax_periods = plt.subplots(figsize=(12, 6))
    fig_prediction, ax_prediction = plt.subplots(figsize=(12, 6))

    ax_pause = plt.axes([0.7, 0.01, 0.1, 0.075])
    ax_start = plt.axes([0.81, 0.01, 0.1, 0.075])
    btn_pause = Button(ax_pause, 'Pause')
    btn_start = Button(ax_start, 'Start')
    btn_pause.on_clicked(toggle_running)
    btn_start.on_clicked(toggle_running)

    ax_pause_chirp = plt.axes([0.7, 0.1, 0.1, 0.075])
    ax_start_chirp = plt.axes([0.81, 0.1, 0.1, 0.075])
    btn_pause_chirp = Button(ax_pause_chirp, 'Pause Chirp')
    btn_start_chirp = Button(ax_start_chirp, 'Start Chirp')
    btn_pause_chirp.on_clicked(toggle_running_chirp)
    btn_start_chirp.on_clicked(toggle_running_chirp)

    try:
        frame_index = 0
        frame_index2 = 0
        chirp_index = 0
        profile_index = 0  

        prev_length_0 = len(timestamps_0)
        prev_length_1 = len(timestamps_1)
        last_used = None
        
        while plt.fignum_exists(fig.number) and plt.fignum_exists(fig_chirp.number):
            if running:
                if profile_index == 0:
                    range_fft(adc_data_profile_0[:, :, frame_index, :], range_data_0, num_samples_0, num_chirps_0, num_rx_0, win_hann_0, dbfs_coeff_0)
                    range_magnitude = range_data_0[:, :, rx_channel]
                    line1.set_ydata(range_magnitude[:, chirp_index])
                    plot_adc_data(ax2, line_real, line_imag, adc_data_profile_0, num_samples_0, num_chirps_0, frame_index, chirp_index, rx_channel, frame_periodicity_0, sample_rate_0, idle_time_0, adc_start_time_0, ramp_time_0, freq_0, profile_index)
                else:
                    range_fft(adc_data_profile_1[:, :, frame_index, :], range_data_1, num_samples_1, num_chirps_1, num_rx_1, win_hann_1, dbfs_coeff_1)
                    range_magnitude = range_data_1[:, :, rx_channel]
                    line1.set_ydata(range_magnitude[:, chirp_index])
                    plot_adc_data(ax2, line_real, line_imag, adc_data_profile_1, num_samples_1, num_chirps_1, frame_index, chirp_index, rx_channel, frame_periodicity_1, sample_rate_1, idle_time_1, adc_start_time_1, ramp_time_1, freq_1, profile_index)

                ax1.set_title(f'Range FFT (Profile {profile_index})')
                ax1.relim()
                ax1.autoscale_view()

                plot_2d_fft_3d(ax3, adc_data_profile_0 if profile_index == 0 else adc_data_profile_1, num_samples_0 if profile_index == 0 else num_samples_1, num_chirps_0 if profile_index == 0 else num_chirps_1, rx_channel, frame_index, range_res_0 if profile_index == 0 else range_res_1)
                plot_2d_fft_image(ax4, adc_data_profile_0 if profile_index == 0 else adc_data_profile_1, num_samples_0 if profile_index == 0 else num_samples_1, num_chirps_0 if profile_index == 0 else num_chirps_1, num_frames_0 if profile_index == 0 else num_frames_1, rx_channel, frame_index, range_res_0 if profile_index == 0 else range_res_1)

                range_doppler_data = compute_range_doppler(adc_data_profile_0 if profile_index == 0 else adc_data_profile_1, num_samples_0 if profile_index == 0 else num_samples_1, num_chirps_0 if profile_index == 0 else num_chirps_1, num_frames_0 if profile_index == 0 else num_frames_1)
                plot_range_doppler(ax6, range_doppler_data, v_max_0 if profile_index == 0 else v_max_1, v_res_0 if profile_index == 0 else v_res_1, num_samples_0 if profile_index == 0 else num_samples_1, num_chirps_0 if profile_index == 0 else num_chirps_1, range_res_0 if profile_index == 0 else range_res_1, frame_index)

                plt.draw()
                plt.pause(0.1)  
                
                profile_index = (profile_index + 1) % 2
                frame_index = (frame_index + 1) % num_frames_0  
            else:
                plt.pause(0.1)
            
            if running_chirp:
                plot_adc_data(ax_chirp, line_real_chirp, line_imag_chirp, adc_data_profile_0 if profile_index == 0 else adc_data_profile_1, num_samples_0 if profile_index == 0 else num_samples_1, num_chirps_0 if profile_index == 0 else num_chirps_1, frame_index2, chirp_index, rx_channel, frame_periodicity_0 if profile_index == 0 else frame_periodicity_1, sample_rate_0 if profile_index == 0 else sample_rate_1, idle_time_0 if profile_index == 0 else idle_time_1, adc_start_time_0 if profile_index == 0 else adc_start_time_1, ramp_time_0 if profile_index == 0 else ramp_time_1, freq_0 if profile_index == 0 else freq_1, profile_index)
                plt.draw()
                plt.pause(0.1)
                
                profile_index = (profile_index + 1) % 2
                if profile_index == 0:
                    chirp_index = (chirp_index + 1) % num_chirps_0
                    if chirp_index == 0:
                        frame_index2 = (frame_index2 + 1) % num_frames_0
            else:
                plt.pause(0.1)  

            if len(timestamps_0) > 1 and len(timestamps_1) > 1:
                if last_used is None or (len(timestamps_0) > prev_length_0 and last_used == 1) or (len(timestamps_1) > prev_length_1 and last_used == 0):
                    if timestamps_0[-1][0] > timestamps_1[-1][0]:
                        unique_periods_0, counts_0 = analyze_periods(timestamps_0)
                        print(unique_periods_0, counts_0, 0)
                        plot_periods(ax_periods, unique_periods_0, counts_0)
                        next_interference_time_0, lower_bound_0, upper_bound_0, profile_0 = predict_next_interference(timestamps_0, unique_periods_0, counts_0, frame_periodicity_0, idle_time_0, adc_start_time_0, 0)
                        plot_prediction(ax_prediction, next_interference_time_0, lower_bound_0, upper_bound_0, timestamps_0, frame_periodicity_0, idle_time_0, adc_start_time_0, unique_periods_0, counts_0, profile_0)
                        last_used = 0
                    else:
                        unique_periods_1, counts_1 = analyze_periods(timestamps_1)
                        print(unique_periods_1, counts_1, 1)   
                        plot_periods(ax_periods, unique_periods_1, counts_1)
                        next_interference_time_1, lower_bound_1, upper_bound_1, profile_1 = predict_next_interference(timestamps_1, unique_periods_1, counts_1, frame_periodicity_1, idle_time_1, adc_start_time_1, 1)
                        plot_prediction(ax_prediction, next_interference_time_1, lower_bound_1, upper_bound_1, timestamps_1, frame_periodicity_1, idle_time_1, adc_start_time_1, unique_periods_1, counts_1, profile_1)
                        last_used = 1

                    prev_length_0 = len(timestamps_0)
                    prev_length_1 = len(timestamps_1)

        print("Timestamps when amplitude went beyond threshold:", timestamps_0, timestamps_1)
        print(timestamps_0)

    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
