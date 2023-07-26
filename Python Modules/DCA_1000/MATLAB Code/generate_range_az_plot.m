function  generate_range_az_plot(mmWave_device,adc_data_cube,ranges,chirp,frame)
    %determine the angular coordinates and the associated AoA
    num_angle_bins = 64;
    angles = (-1 * pi:2 * pi/(num_angle_bins - 1):pi) * -1;
    AoA_coordinates_rad = asin(angles/pi);
    
    %define the amount of zero padding to add
    range_angle_cube = zeros(mmWave_device.num_sample_per_chirp,num_angle_bins);
    
    %obtain the frame data
    frame_data = adc_data_cube(:,:,chirp,frame).';
    range_angle_cube(:,1:mmWave_device.num_rx_chnl) = fft(mmWave_device.win_hann .* frame_data);
    range_angle_cube = fftshift(fft(range_angle_cube,num_angle_bins,2),2);
    % 
    % frame_data = 20*log10(abs(fft_2d_range_cube(:,:,desired_frame)));
    x_vals = AoA_coordinates_rad;
    % imagesc(x_vals,ranges, 20 * log10(abs(range_angle_cube)));
    [thetas,rhos] = meshgrid(AoA_coordinates_rad,ranges);
    [X,Y] = pol2cart(thetas,rhos);
    surf(X,Y, 20 * log10(abs(range_angle_cube)) + mmWave_device.dbfs_coeff,'EdgeColor','none');
    view(90,270)
    %title_str = sprintf('2D Range FFT for frame: %d',desired_frame);
    title("Range-Azimuth Plot");
    xlabel('Range')
    ylabel('Range(m)')
    zlabel('Magnitude (dB)')
    colorbar;
end