import numpy as np
import time

try:
    import soundfile
    HAS_SOUNDFILE = True
except ImportError:
    HAS_SOUNDFILE = False


from .invcgc import InvCGC



def make_processing_loop(ProcessingClass, in_buffer, chunksize, sample_rate, dtype='float32', 
            processing_conf={}, buffersize_margin=0, time_stats=True):
    
    nb_channel = in_buffer.shape[1]
    buffer_size = in_buffer.shape[0]
    buffer_size2 = in_buffer.shape[0] + buffersize_margin
    
    
    processing = ProcessingClass(nb_channel=nb_channel, sample_rate=sample_rate, dtype=dtype, **processing_conf)
    
    def loop():
        if time_stats:
            time_durations = []
            start0 = time.perf_counter()
        nloop = buffer_size//chunksize
        index = 0
        out_index = None
        while out_index is None or out_index<buffer_size:
            index += chunksize
            
            if index<=buffer_size:
                in_chunk = in_buffer[index-chunksize:index, :]
            else:
                in_chunk = np.zeros((chunksize, in_buffer.shape[1]), dtype=dtype)
            
            if time_stats:
                t0 = time.perf_counter()
            
            returns = processing.proccesing_func(index, in_chunk)
            if time_stats:
                time_durations.append(time.perf_counter()-t0)
            
            out_index, out_chunk = returns['main_output']
            
            yield returns
        
        if time_stats:
            duration = time.perf_counter() - start0
            time_durations = np.array(time_durations)
            print('buffer duration {:0.3f}s total compute {:0.3f}s  speed {:0.1f}'.format(buffer_size/sample_rate,
                                                                            duration, buffer_size/sample_rate/duration))
            print('chunksize time:  {:0.1f}ms nloop {}'.format(chunksize/sample_rate*1000, time_durations.size))
            print('Compute time Mean: {:0.1f}ms Min: {:0.1f}ms Max: {:0.1f}ms'.format( time_durations.mean()*1000.,
                                                                            time_durations.min()*1000., time_durations.max()*1000.))
            nb_too_slow = np.sum(time_durations>(chunksize/sample_rate))
            print('nb_too_slow {}  ({:0.1f}%)'.format(nb_too_slow, nb_too_slow/time_durations.size*100.))
    
    
    return processing, loop
    
def run_one_class_offline(ProcessingClass, in_buffer, chunksize, sample_rate, dtype='float32', 
            processing_conf={}, buffersize_margin=0, time_stats=True):
    
    processing, loop = make_processing_loop(ProcessingClass, in_buffer, chunksize, sample_rate,  dtype=dtype, 
            processing_conf=processing_conf, buffersize_margin=buffersize_margin, time_stats=time_stats)
    
    buffer_size = in_buffer.shape[0]
    
    online_arrs = {}
    for returns in loop():
        for k, (pos, out_chunk) in returns.items():
            if k not in online_arrs and pos is not None:
                online_arrs[k] = np.zeros((buffer_size, out_chunk.shape[1]), dtype=dtype)
            
            if pos is not None:
                #~ print('pos', pos, 'k', k, out_chunk.shape)
                if online_arrs[k][pos-out_chunk.shape[0]:pos, :].shape[0]==out_chunk.shape[0]:
                    online_arrs[k][pos-out_chunk.shape[0]:pos, :] = out_chunk
    
    return processing, online_arrs
    


def compute_numpy(sound, sample_rate, **params):
    """
    Run InvCGC offline on a numpy buffer.
    
    Parameters
    ---
        sound: sound shape (len, nb_channel)
        sample_rate: the sample rate
        **params: see `InvCGC`.`configure()`
        
        
    """
    assert isinstance(sound, np.ndarray)
    
    if sound.ndim==1:
        sound = sound[:, None]
        onedim = True
    else:
        onedim = False
    
    sound = sound.astype('float32')

    chunksize = params['chunksize']
    backward_chunksize =  params['backward_chunksize']
    
    processing, online_arrs = run_one_class_offline(InvCGC, sound, chunksize, sample_rate, processing_conf=params, dtype='float32', 
            buffersize_margin=backward_chunksize, time_stats=False)

    out_sound = online_arrs['main_output']
    
    if onedim:
        out_sound = out_sound[:, 0]
    
    return out_sound



class WaveNumpy:
    """
    Fake numpy buffer?
    """
    def __init__(self, wav_filename):
        self.file = soundfile.SoundFile(wav_filename, 'r', )
        self.shape = (len(self.file), self.file.channels)
    
    def __getitem__(self, sl):
        assert isinstance(sl, tuple)
        assert len(sl) == 2
        sl0, sl1 = sl[0], sl[1]
        assert sl0.step is None
        self.file.seek(sl0.start)
        buf = self.file.read(frames=sl0.stop-sl0.start,dtype='float32', always_2d=True)
        buf = buf[:, sl1]
        return buf
        
        
        

def compute_wave_file(in_filename, out_filename, duration_limit=None, **params):
    """
    Run InvCGC offline on a wave file.
    
    Parameters
    ---
        in_filename: input file name
        out_filename: output file name
        duration_limit: clip the duration. None (default) means all the file.
        **params: see `InvCGC`.`configure()`
        
        
    """    
    assert HAS_SOUNDFILE, 'soundfile need to be installed'
    
    assert in_filename != out_filename
    in_buffer = WaveNumpy(in_filename)
    in_wav = in_buffer.file
    out_wav = soundfile.SoundFile(out_filename, 'w', channels=in_wav.channels, samplerate=in_wav.samplerate, subtype='FLOAT')
    
    sample_rate = float(in_wav.samplerate)
    
    nb_channel = in_wav.channels
    chunksize = params['chunksize']
    backward_chunksize =  params['backward_chunksize']
    if len(params['loss_params'])<nb_channel:
        params['loss_params']['right'] = dict(params['loss_params']['left'])
    
    
    processing, loop = make_processing_loop(InvCGC, in_buffer, chunksize, sample_rate, dtype='float32', 
            processing_conf=params, buffersize_margin=0, time_stats=False)
    
    for i, returns in enumerate(loop()):
        out_index, processed_data = returns['main_output']
        
        if processed_data is not None:
            out_wav.write(processed_data)
        
        if duration_limit is not None and out_index is not None and\
                out_index/sample_rate>=duration_limit:
            #~ print('break')
            break


