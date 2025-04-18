import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import scipy.signal as signal
import cv2
from numpy.lib.stride_tricks import sliding_window_view
import torch.nn as nn
import torch
from scipy.interpolate import interp1d

class SpgrmFilter:
    def __init__(self, ppg_fr, in_signal, len_ppg, min_amplitude=4, min_len_interval=64, window_size=256):
        self.ppg_fr = ppg_fr
        self.in_signal=in_signal
        self.len_ppg=len_ppg
        self.min_amplitude=min_amplitude
        self.min_len_interval=min_len_interval
        self.window_size=window_size


    def apply_filter(self, ppg_md):
        ppg_filt = self.__bandpass_filter(ppg_md, 0.8, 4, self.ppg_fr)
        adapt_ppg = self.__adaptive_normalization(ppg_filt)

        wight = len(adapt_ppg) / 512
        img = self.__spgrm(adapt_ppg)
        out = self.__conv(img)
        mean_fr = self.__compute_windowed_mean(out)
        mask = self.__create_mask()
        filt_ppg = adapt_ppg.copy()
        filt_ppg[~mask] = 0
        
        return filt_ppg


    def __bandpass_filter(self, data, lowcut, highcut, fs, order=3):
        nyquist = 0.5 * fs
        low = lowcut / nyquist
        high = highcut / nyquist
        b, a = signal.butter(order, [low, high], btype='band')
        return signal.filtfilt(b, a, data)
    

    def __adaptive_normalization(self, data):
        normalized = np.zeros_like(data)

        for i in range(len(data)):
            start = max(0, i - self.window_size // 2)
            end = min(len(data), i + self.window_size // 2)

            local_mean = np.mean(data[start:end])
            local_std = np.std(data[start:end])

            normalized[i] = (data[i] - local_mean) / local_std
            
        return normalized
    

    def __compute_windowed_mean(self, spectrogram):
        window_width = spectrogram.shape[0]
        windows = sliding_window_view(spectrogram, window_shape=window_width, axis=1)
        
        return np.mean(windows, axis=(0, 2))
    

    def __norm_spgrm(self, img):
        mean = np.mean(img)
        centered = img - mean
        std = np.std(centered)
        return centered / std
    

    def __spgrm(self, ppg, min_fr=0, max_fr=3):
        frequencies, _, Zxx = signal.stft(ppg, fs=256, window='hann', nperseg=1024, noverlap=1000)

        # log_spectrogram = 20 * np.log10(np.abs(Zxx) + 1e-10)
        log_spectrogram = np.abs(Zxx)
        freq_mask = (frequencies >= min_fr) & (frequencies <= max_fr)
        img = self.__norm_spgrm(log_spectrogram[freq_mask, : ])

        return img
        
    def __conv(self, img):
        kernel_row = np.array(
            [[-1, -1, -1, -1, -1, -1, -1, -1, -1],
            # [-1, -1, -1, -1, -1, -1, -1, -1, -1],
            [0, 0, 0, 0, 0, 0, 0, 0, 0],
            # [1, 1, 1, 1, 1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1, 1, 1, 1, 1]],
        dtype=np.float32)

        conv1 = cv2.filter2D(img, -1, kernel_row)
        # conv2 = cv2.filter2D(conv1, -1, kernel_row)

        # relu = nn.ReLU()
        gelu = nn.GELU()
        activate = gelu(torch.Tensor(conv1))
        # activate = np.log10(relu(torch.Tensor(conv1)) + 1)

        return activate
    
    def __create_mask(self):
        valid = (self.in_signal >= self.min_amplitude)
        
        diff = np.diff(valid.astype(int))
        starts = np.where(diff == 1)[0] + 1
        ends = np.where(diff == -1)[0] + 1

        if valid[0]:
            starts = np.insert(starts, 0, 0)
        if valid[-1]:
            ends = np.append(ends, len(valid))
        
        intervals = []
        for s, e in zip(starts, ends):
            if e - s >= self.min_len_interval:
                intervals.append((s, e))
        
        time_mask = np.zeros_like(valid, dtype=bool)
        for s, e in intervals:
            time_mask[s:e] = True

        indices_mask = np.arange(len(time_mask))
        indices_ppg = np.linspace(0, len(time_mask)-1, self.len_ppg)
        
        mask_func = interp1d(
            indices_mask,
            time_mask,
            kind='nearest',
            bounds_error=False,
            fill_value=False
        )
        
        return mask_func(indices_ppg).astype(bool)


