import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import Slider, Button
from MMWaveDevice import MMWaveDevice
from scipy.signal import find_peaks
from sklearn.cluster import DBSCAN
import matplotlib.ticker as ticker

play_chirp_active = False
play_frame_active = False

timestamps_0 = []
timestamps_1 = []

prev_interference_times_0 = []
prev_bounds_0 = []

prev_interference_times_1 = []
prev_bounds_1 = []

last_used = None

prev_length_0 = 0
prev_length_1 = 0

frame_shift = False
chirp_changed = False
frame_changed = False

def read_adc_data(adc_data_bin_file, mmwave_device_0, mmwave_device_1):
    num_samples_0 = mmwave_device_0.num_sample_per_chirp
    num_samples_1 = mmwave_device_1.num_sample_per_chirp
    num_chirps_0 = mmwave_device_0.num_chirp_per_frame 
    num_chirps_1 = mmwave_device_1.num_chirp_per_frame
    num_frames = mmwave_device_0.num_frame #
    num_rx = mmwave_device_0.num_rx_chnl  
    num_lanes = 4  

    adc_data = np.fromfile(adc_data_bin_file, dtype=np.int16)
    expected_size = (num_samples_0 * (num_chirps_0) + num_chirps_1 * num_samples_1) * num_frames * num_rx * 2
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

def analyze_periods(timestamps):
    timestamps = np.array([t[0] for t in timestamps]) 
    periods = np.diff(timestamps) 

    periods = np.round(periods, 4)

    periods_reshaped = periods.reshape(-1, 1)
    dbscan = DBSCAN(eps=0.005, min_samples=5).fit(periods_reshaped)
    labels = dbscan.labels_

    unique_labels, counts = np.unique(labels, return_counts=True)
    main_cluster_label = unique_labels[np.argmax(counts)]

    filtered_periods = periods[labels == main_cluster_label]
    outliers = periods[labels != main_cluster_label]
    print("Outliers:", outliers)

    unique_periods, counts = np.unique(filtered_periods, return_counts=True)

    return unique_periods, counts

def analyze_slopes(timestamps):
    times = np.array([t[0] for t in timestamps])
    freqs = np.array([t[1] for t in timestamps])
    
    slopes = np.diff(freqs) / np.diff(times)
    
    slopes_reshaped = slopes.reshape(-1, 1)
    dbscan = DBSCAN(eps=0.01, min_samples=5).fit(slopes_reshaped)
    labels = dbscan.labels_

    unique_labels, counts = np.unique(labels, return_counts=True)
    main_cluster_label = unique_labels[np.argmax(counts)]

    filtered_slopes = slopes[labels == main_cluster_label]
    outliers = slopes[labels != main_cluster_label]
    print("Slope Outliers:", outliers)

    unique_slopes, counts = np.unique(filtered_slopes, return_counts=True)

    return unique_slopes, counts

def analyze_interference_batches(timestamps):
    batches = []
    batch_start_indices = [0]
    
    for i in range(1, len(timestamps)):
        if timestamps[i][0] - timestamps[i-1][0] > 50:  
            batch_start_indices.append(i)

    batch_start_times = [timestamps[i][0] for i in batch_start_indices]
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
    print("Batch Period Outliers:", outliers)

    unique_batch_periods, counts = np.unique(filtered_batch_periods, return_counts=True)

    return unique_batch_periods, counts

def predict_next_interference(timestamps, unique_periods, counts, frame_periodicity, idle_time, adc_start_time, profile, ramp_time):
    if len(unique_periods) > 0 and counts.max() >= 4:
        mean_period = np.mean(unique_periods)
        last_timestamp = timestamps[-1][0]
        next_interference_time = last_timestamp + mean_period
        print(last_timestamp, mean_period)
        print("Next Interference Time:", next_interference_time)
        lower_bound = next_interference_time - 0.025
        upper_bound = next_interference_time + 0.025


        n = int(next_interference_time // frame_periodicity)
        remaining_time = next_interference_time - frame_periodicity * n
        chirp_number = int(remaining_time // ((idle_time + ramp_time) ))
        start_time = frame_periodicity * n + (chirp_number )* (idle_time + ramp_time) + idle_time + adc_start_time
        end_time = frame_periodicity * n + (chirp_number+1) * (idle_time + ramp_time)
        print("Start Time:", start_time)
        print("End Time:", end_time)
        print("Next Interference Time:", next_interference_time)

        if start_time <= next_interference_time <= end_time:
            return next_interference_time, lower_bound, upper_bound, profile

    return None, None, None, None

def plot_prediction(ax, next_interference_time, lower_bound, upper_bound, timestamps, frame_periodicity, idle_time, adc_start_time, unique_periods, counts, profile, ramp_time):
    global prev_interference_times_0, prev_bounds_0, prev_interference_times_1, prev_bounds_1
    ax.clear()

    times_0 = [t[0] for t in timestamps_0]
    freqs_0 = [t[1] for t in timestamps_0]
    times_1 = [t[0] for t in timestamps_1]
    freqs_1 = [t[1] for t in timestamps_1]

    ax.plot(times_0, freqs_0, 'o', label='Profile 0 Interference Times', color='blue')
    ax.plot(times_1, freqs_1, 'o', label='Profile 1 Interference Times', color='orange')

    print(prev_interference_times_0)
    for interference_time, bounds in zip(prev_interference_times_0, prev_bounds_0):
        if interference_time is not None:
            if bounds:

                n = int(interference_time // frame_periodicity)
                remaining_time = interference_time - frame_periodicity * n
                chirp_number = int(remaining_time // ((idle_time + ramp_time) ))
                start_time = frame_periodicity * n + (chirp_number )* (idle_time + ramp_time) + idle_time + adc_start_time
                end_time = frame_periodicity * n + (chirp_number+1) * (idle_time + ramp_time)
                good_range_start = max(bounds[0], start_time)
                good_range_end = min(bounds[1], end_time)
                if good_range_start < good_range_end:
                    if interference_time < good_range_start or interference_time > good_range_end:
                        print("Error: Previous interference time out of bounds.")
                    ax.axvline(interference_time, ymin=0, ymax=0.5, color='g', linestyle='--')
                    ax.fill_betweenx([freqs_0[0] - 0.5, freqs_0[0] + 0.5], good_range_start, good_range_end, color='g', alpha=0.3)

    for interference_time, bounds in zip(prev_interference_times_1, prev_bounds_1):
        if interference_time is not None:
            if bounds:
                n = int(interference_time // frame_periodicity)
                remaining_time = interference_time - frame_periodicity * n
                chirp_number = int(remaining_time // ((idle_time + ramp_time) ))
                start_time = frame_periodicity * n + (chirp_number )* (idle_time + ramp_time) + idle_time + adc_start_time
                end_time = frame_periodicity * n + (chirp_number+1) * (idle_time + ramp_time)
                good_range_start = max(bounds[0], start_time)
                good_range_end = min(bounds[1], end_time)
                if good_range_start < good_range_end:
                    ax.axvline(interference_time, ymin=0.5, ymax=1.0, color='g', linestyle='--')
                    ax.fill_betweenx([freqs_1[0] - 0.5 , freqs_1[0] + 0.5], good_range_start, good_range_end, color='g', alpha=0.3)

    prev_interference_times = (prev_interference_times_0 + prev_interference_times_1)
    prev_interference_times.sort()

    if next_interference_time is not None and (prev_interference_times == [] or next_interference_time >= prev_interference_times[-1] + idle_time * 10 + 0.5):
        good_range_start = max(lower_bound, frame_periodicity * (next_interference_time // frame_periodicity) + idle_time + adc_start_time)
        good_range_end = min(upper_bound, frame_periodicity * (next_interference_time // frame_periodicity + 1))
        if good_range_start < good_range_end:
            if profile == 0:
                ax.axvline(next_interference_time, ymin=0, ymax=0.5, color='r', linestyle='--', label='Predicted Next Interference', linewidth=2)
                ax.fill_betweenx([freqs_0[0] - 0.5, freqs_0[0] + 0.5], good_range_start, good_range_end, color='r', alpha=0.3, label='Prediction Range')
                prev_interference_times_0.append(next_interference_time)
                prev_bounds_0.append((lower_bound, upper_bound))
                if next_interference_time < lower_bound or next_interference_time > upper_bound:
                    print("Error: Next interference time out of bounds.")
            else:
                ax.axvline(next_interference_time, ymin=0.5, ymax=1.0, color='r', linestyle='--', label='Predicted Next Interference', linewidth=2)
                ax.fill_betweenx([freqs_1[0] - 0.5 , freqs_1[0] + 0.5], good_range_start, good_range_end, color='r', alpha=0.3, label='Prediction Range')
                prev_interference_times_1.append(next_interference_time)
                prev_bounds_1.append((lower_bound, upper_bound))

    if len(unique_periods) > 0 and counts.max() >= 4:
        mean_period = np.mean(unique_periods)
        window_size = mean_period * 20
    else:
        window_size = 10

    current_time = max(times_0 + times_1) if (times_0 + times_1) else 0
    ax.set_xlim([max(0, current_time - window_size), current_time + window_size / 10 + 1e-6])
    ax.set_ylim([freqs_0[0] - 1, freqs_1[0] + 1])
    ax.set_title('Prediction of Next Interference')
    ax.set_xlabel('Time (10$^{-4}$ seconds)')
    ax.set_ylabel('Frequency (GHz)')
    ax.legend()
    plt.draw()

    
def plot_scrollable_adc_data(adc_data, num_samples, num_chirps, num_frames, rx_channel, sample_rate, frame_periodicity, idle_time, ramp_time, adc_start_time, mmwave_devices):
    global play_chirp_active, play_frame_active, timestamps_0, timestamps_1

    fig, (ax, ax_freq, ax_hist) = plt.subplots(3, 1, figsize=(12, 18))
    plt.subplots_adjust(bottom=0.25, hspace=0.4)

    chirp_view = 3

    line_real, = ax.plot([], [], label='Real')
    line_imag, = ax.plot([], [], label='Imaginary')
    ax.set_xlabel('Time (ms)')
    ax.set_ylabel('Amplitude')
    ax.legend()

    freq_line, = ax_freq.plot([], [], 'o', label='Detected Frequency Peaks')
    ax_freq.set_xlabel('Time (ms)')
    ax_freq.set_ylabel('Frequency (GHz)')
    ax_freq.legend()

    ax_hist.set_xlabel('Period (ms)')
    ax_hist.set_ylabel('Frequency')
    ax_hist.set_title('Histogram of Detected Periods')

    def update(val):
        global timestamps_0, timestamps_1, last_used, prev_length_0, prev_length_1
        frame_idx = int(slider_frame.val)
        chirp_start = int(slider_chirp.val)
        chirp_end = chirp_start + chirp_view

        plot_data_real = []
        plot_data_imag = []
        times = []

        for chirp_idx in range(chirp_start, min(chirp_end, num_chirps[0])):

            chirp_data_0 = adc_data[0][:, chirp_idx, frame_idx, rx_channel]
            chirp_data_1 = adc_data[1][:, chirp_idx, frame_idx, rx_channel]

            time_per_sample = 1 / sample_rate[0]
            start_time_0 = frame_idx * frame_periodicity[0] + (2 * chirp_idx) * (idle_time[0] + ramp_time[0]) + (idle_time[0] + adc_start_time[0])
            num_samples_current = num_samples[0]

            start_time_1 = frame_idx * frame_periodicity[1] + (2 * chirp_idx + 1) * (idle_time[1] + ramp_time[1]) + (idle_time[1] + adc_start_time[1])

            time_indices_0 = start_time_0 + np.arange(num_samples_current) * time_per_sample
            time_indices_1 = start_time_1 + np.arange(num_samples[1]) * time_per_sample

            plot_data_real.extend(chirp_data_0.real)
            plot_data_imag.extend(chirp_data_0.imag)
            times.extend(time_indices_0)

            if chirp_idx < min(chirp_end, num_chirps[0]):
                plot_data_real.append(np.nan)
                plot_data_imag.append(np.nan)
                times.append(np.nan)

            plot_data_real.extend(chirp_data_1.real)
            plot_data_imag.extend(chirp_data_1.imag)
            times.extend(time_indices_1)

            if chirp_idx < min(chirp_end, num_chirps[0]) - 1:
                plot_data_real.append(np.nan)
                plot_data_imag.append(np.nan)
                times.append(np.nan)

            complex_magnitude_0 = np.abs(chirp_data_0)
            complex_magnitude_1 = np.abs(chirp_data_1)
            thresholds_0 = (np.mean(complex_magnitude_0) + 5 * np.std(complex_magnitude_0)) * 1.3
            thresholds_1 = (np.mean(complex_magnitude_1) + 5 * np.std(complex_magnitude_1)) * 1.3

            for magnitude, time_index in zip(complex_magnitude_0, time_indices_0):
                if magnitude > thresholds_0:
                    if not any(np.isclose(time_index, t[0]) for t in timestamps_0):
                        timestamps_0.append((time_index, mmwave_devices[0].freq /1e9))

            for magnitude, time_index in zip(complex_magnitude_1, time_indices_1):
                if magnitude > thresholds_1:
                    if not any(np.isclose(time_index, t[0]) for t in timestamps_1):
                        timestamps_1.append((time_index, mmwave_devices[1].freq /1e9))

        line_real.set_data(times, plot_data_real)
        line_imag.set_data(times, plot_data_imag)
        ax.set_title(f'ADC Data for Frame {frame_idx}, Chirps {chirp_start} to {chirp_end - 1}')
        ax.relim()
        ax.autoscale_view()



        if len(timestamps_0) > 1:
            timestamps_0.sort(key=lambda x: x[0])
            times_peaks_0, freqs_peaks_0 = zip(*timestamps_0)
            freq_line.set_data(times_peaks_0, [f for f in freqs_peaks_0])
            ax_freq.set_yticks([f for f in freqs_peaks_0])
            ax_freq.set_yticklabels([f'{f:.1f}' for f in freqs_peaks_0])
            ax_freq.set_title('Slope and Period Estimation')
            ax_freq.relim()
            ax_freq.autoscale_view()
            # min_freq = min(freqs_peaks_0)
            # max_freq = max(freqs_peaks_0)
            # ax_freq.set_ylim(min_freq - 0.5, max_freq + 0.5)

            periods_0 = np.diff(times_peaks_0)
            if np.any(periods_0 <= 0):
                print("Error: Detected non-positive periods.")
            unique_periods_0, counts_0 = analyze_periods(timestamps_0)
            ax_hist.clear()
            ax_hist.hist(unique_periods_0, bins=20, weights=counts_0, edgecolor='black')
            ax_hist.set_xlabel('Period (ms)')
            ax_hist.set_ylabel('Frequency')
            ax_hist.set_title('Histogram of Detected Periods (Profile 0)')

            # if last_used == None or (len(timestamps_0) > prev_length_0 and last_used == 1):
            #     next_interference_time_0, lower_bound_0, upper_bound_0, profile_0 = predict_next_interference(timestamps_0, unique_periods_0, counts_0, frame_periodicity[0], idle_time[0], adc_start_time[0], 0)
            #     plot_prediction(ax_freq, next_interference_time_0, lower_bound_0, upper_bound_0, timestamps_0, frame_periodicity[0], idle_time[0], adc_start_time[0], unique_periods_0, counts_0, profile_0)
            #     last_used = 0
            # # next_interference_time_0, lower_bound_0, upper_bound_0, profile_0 = predict_next_interference(timestamps_0, unique_periods_0, counts_0, frame_periodicity[0], idle_time[0], adc_start_time[0], 0)
            # # plot_prediction(ax_freq, next_interference_time_0, lower_bound_0, upper_bound_0, timestamps_0, frame_periodicity[0], idle_time[0], adc_start_time[0], unique_periods_0, counts_0, profile_0)
            # prev_length_0 = len(timestamps_0)

        if len(timestamps_1) > 1:
            timestamps_1.sort(key=lambda x: x[0])
            times_peaks_1, freqs_peaks_1 = zip(*timestamps_1)
            freq_line.set_data(times_peaks_1, [f for f in freqs_peaks_1])
            ax_freq.set_yticks([f for f in freqs_peaks_1])
            ax_freq.set_yticklabels([f'{f:.1f}' for f in freqs_peaks_1])
            ax_freq.set_title('Slope and Period Estimation')
            ax_freq.relim()
            ax_freq.autoscale_view()
            # min_freq = min(freqs_peaks_1)
            # max_freq = max(freqs_peaks_1)
            # ax_freq.set_ylim(min_freq - 0.5, max_freq + 0.5)

            periods_1 = np.diff(times_peaks_1)
            if np.any(periods_1 <= 0):
                print("Error: Detected non-positive periods.")
            unique_periods_1, counts_1 = analyze_periods(timestamps_1)
            ax_hist.clear()
            ax_hist.hist(unique_periods_1, bins=20, weights=counts_1, edgecolor='black')
            ax_hist.set_xlabel('Period (ms)')
            ax_hist.set_ylabel('Frequency')
            ax_hist.set_title('Histogram of Detected Periods (Profile 1)')

            # if last_used == None or (len(timestamps_1) > prev_length_1 and last_used == 0):
            #     next_interference_time_1, lower_bound_1, upper_bound_1, profile_1 = predict_next_interference(timestamps_1, unique_periods_1, counts_1, frame_periodicity[1], idle_time[1], adc_start_time[1], 1)
            #     plot_prediction(ax_freq, next_interference_time_1, lower_bound_1, upper_bound_1, timestamps_1, frame_periodicity[1], idle_time[1], adc_start_time[1], unique_periods_1, counts_1, profile_1)
            #     last_used = 1
            
            # prev_length_1 = len(timestamps_1)
                
            # next_interference_time_1, lower_bound_1, upper_bound_1, profile_1 = predict_next_interference(timestamps_1, unique_periods_1, counts_1, frame_periodicity[1], idle_time[1], adc_start_time[1], 1)
            # plot_prediction(ax_freq, next_interference_time_1, lower_bound_1, upper_bound_1, timestamps_1, frame_periodicity[1], idle_time[1], adc_start_time[1], unique_periods_1, counts_1, profile_1)

        
        if len(timestamps_0) > 1 and len(timestamps_1) > 1:
            print("A")
            if last_used is None or (len(timestamps_0) > prev_length_0 and last_used == 1 ) or (len(timestamps_1) > prev_length_1 and last_used == 0):
                if last_used == 1:
                    unique_periods_0, counts_0 = analyze_periods(timestamps_0)
                    print(unique_periods_0, counts_0, 0)
                    next_interference_time_0, lower_bound_0, upper_bound_0, profile_0 = predict_next_interference(timestamps_0, unique_periods_0, counts_0, frame_periodicity[0], idle_time[0], adc_start_time[0], 0, ramp_time[0])
                    plot_prediction(ax_freq, next_interference_time_0, lower_bound_0, upper_bound_0, timestamps_0, frame_periodicity[0], idle_time[0], adc_start_time[0], unique_periods_0, counts_0, profile_0, ramp_time[0])
                    last_used = 0
                else:
                    unique_periods_1, counts_1 = analyze_periods(timestamps_1)
                    print(unique_periods_1, counts_1, 1)   
                    next_interference_time_1, lower_bound_1, upper_bound_1, profile_1 = predict_next_interference(timestamps_1, unique_periods_1, counts_1, frame_periodicity[1], idle_time[1], adc_start_time[1], 1, ramp_time[1])
                    plot_prediction(ax_freq, next_interference_time_1, lower_bound_1, upper_bound_1, timestamps_1, frame_periodicity[1], idle_time[1], adc_start_time[1], unique_periods_1, counts_1, profile_1, ramp_time[1])
                    last_used = 1
                

                prev_length_0 = len(timestamps_0)
                prev_length_1 = len(timestamps_1)
            
        plt.draw()

        if len(timestamps_0 + timestamps_1) > 1:
            timestamp = (timestamps_0 + timestamps_1)
            timestamp.sort(key=lambda x: x[0])
            unique_slope, count = analyze_slopes(timestamp)
            print("Slope")
            print(unique_slope)
            if len(timestamp) > 2:
                unique_batch_periods, count = analyze_interference_batches(timestamp)
                print("Batch Period")
                print(unique_batch_periods)


    slider_frame_ax = plt.axes([0.25, 0.15, 0.65, 0.03], facecolor='lightgoldenrodyellow')
    slider_frame = Slider(slider_frame_ax, 'Frame', 0, num_frames - 1, valinit=0, valstep=1)
    slider_frame.on_changed(update)

    slider_chirp_ax = plt.axes([0.25, 0.1, 0.65, 0.03], facecolor='lightgoldenrodyellow')
    slider_chirp = Slider(slider_chirp_ax, 'Chirp', 0, num_chirps[0] - chirp_view, valinit=0, valstep=chirp_view)
    slider_chirp.on_changed(update)

    play_chirp_ax = plt.axes([0.8, 0.025, 0.1, 0.04])
    play_chirp_button = Button(play_chirp_ax, 'Play Chirp', color='lightgoldenrodyellow', hovercolor='0.975')

    play_frame_ax = plt.axes([0.8, 0.075, 0.1, 0.04])
    play_frame_button = Button(play_frame_ax, 'Play Frame', color='lightgoldenrodyellow', hovercolor='0.975')

    pause_chirp_ax = plt.axes([0.7, 0.025, 0.1, 0.04])
    pause_chirp_button = Button(pause_chirp_ax, 'Pause Chirp', color='lightgoldenrodyellow', hovercolor='0.975')

    pause_frame_ax = plt.axes([0.7, 0.075, 0.1, 0.04])
    pause_frame_button = Button(pause_frame_ax, 'Pause Frame', color='lightgoldenrodyellow', hovercolor='0.975')

    def play_chirp(event):
        global play_chirp_active
        play_chirp_active = True
        while play_chirp_active:
            chirp_idx = int(slider_chirp.val)
            frame_idx = int(slider_frame.val)
            if chirp_idx < num_chirps[0] - chirp_view:
                slider_chirp.set_val(chirp_idx + chirp_view)
            else:
                if frame_idx < num_frames - 1:
                    slider_chirp.set_val(0)
                    print("XD")
                    slider_frame.set_val(frame_idx + 1)
                    print("XD2")
                else:
                    break
            plt.pause(0.1)

    def play_frame(event):
        global play_frame_active
        play_frame_active = True
        while play_frame_active:
            frame_idx = int(slider_frame.val)
            if frame_idx < num_frames - 1:
                slider_frame.set_val(frame_idx + 1)
            else:
                slider_frame.set_val(0)
            plt.pause(0.1)

    def pause_chirp(event):
        global play_chirp_active
        play_chirp_active = False

    def pause_frame(event):
        global play_frame_active
        play_frame_active = False

    play_chirp_button.on_clicked(play_chirp)
    play_frame_button.on_clicked(play_frame)
    pause_chirp_button.on_clicked(pause_chirp)
    pause_frame_button.on_clicked(pause_frame)

    def on_key(event):
        global play_chirp_active, play_frame_active
        if event.key == 'q':
            play_chirp_active = False
            play_frame_active = False
            plt.close('all')

    fig.canvas.mpl_connect('key_press_event', on_key)

    update(0)
    plt.show()

def main():
    adc_data_bin_file = '/Users/edwardju/Downloads/adc_data_45degTest2.bin'
    mmwave_setup_json_file = '/Users/edwardju/Downloads/45degTest2.mmwave.json'

    mmwave_device_profile_0 = MMWaveDevice(adc_data_bin_file, mmwave_setup_json_file, profile_id=0)
    mmwave_device_profile_0.print_device_configuration()

    mmwave_device_profile_1 = MMWaveDevice(adc_data_bin_file, mmwave_setup_json_file, profile_id=1)
    mmwave_device_profile_1.print_device_configuration()

    adc_data_0, adc_data_1 = read_adc_data(adc_data_bin_file, mmwave_device_profile_0, mmwave_device_profile_1)

    num_samples = [mmwave_device_profile_0.num_sample_per_chirp, mmwave_device_profile_1.num_sample_per_chirp]
    num_chirps = [mmwave_device_profile_0.num_chirp_per_frame, mmwave_device_profile_1.num_chirp_per_frame]
    num_frames = mmwave_device_profile_0.num_frame
    rx_channel = 0

    sample_rate = [mmwave_device_profile_0.adc_samp_rate * 1000, mmwave_device_profile_1.adc_samp_rate * 1000]
    frame_periodicity = [mmwave_device_profile_0.frame_periodicity, mmwave_device_profile_1.frame_periodicity]
    idle_time = [mmwave_device_profile_0.chirp_idle_time * 1e-3, mmwave_device_profile_1.chirp_idle_time * 1e-3]
    ramp_time = [mmwave_device_profile_0.chirp_ramp_time * 1e-3, mmwave_device_profile_1.chirp_ramp_time * 1e-3]
    adc_start_time = [mmwave_device_profile_0.chirp_adc_start_time * 1e-3, mmwave_device_profile_1.chirp_adc_start_time * 1e-3]

    plot_scrollable_adc_data([adc_data_0, adc_data_1], num_samples, num_chirps, num_frames, rx_channel, sample_rate, frame_periodicity, idle_time, ramp_time, adc_start_time, [mmwave_device_profile_0, mmwave_device_profile_1])

if __name__ == "__main__":
    main()
