#! /usr/bin/env python


## Support for byteswapping audio streams (needed for AIFF format).

_typecode = {2:'h'}

def _init_typecode():
    import array
    for t in ('i', 'l'):
      a = array.array(t)
      if a.itemsize==4:
        _typecode[4] = t
        return
    import sys
    print "Can't find array typecode for 4 byte ints."
    sys.exit(1)
_init_typecode()

def _byteswap(s,n):
    """Byteswap stream s, which is of width n bytes. Does nothing if n is 1.
       Only supports widths listed in _typecode (2 & 4)."""
    if n==1:
      return s
    import array
    a = array.array( _typecode[n], s )
    a.byteswap()
    return a.tostring()

def _null(s,n):
    """Do nothing to stream s, which is of width n. See also: _byteswap(s,n)"""
    return s


class SoundFile(object):
  '''Wrapper for PCM sound stream, can be AIFF (aifc module)
     or WAV (wave module).'''

  def __init__(self, fname, template_obj=None):
      if fname[-5:].lower() == '.aiff':
        self._mod = __import__('aifc')
        self._conv = _byteswap # AIFF is big-endian.
      elif fname[-4:].lower() == '.wav':
        self._mod = __import__('wave')
        self._conv = _null
      else:
        print 'Unknown extension:', fname
        import sys
        sys.exit(1)
      if template_obj:
        # We will create & write to this file.
        self.init_from_template(fname, template_obj)
      else:
        # We load from this file.
        self.load(fname)

  def bytes_per_frame(self):
      return self.stream.getsampwidth() * self.stream.getnchannels()
  def bytes_per_second(self):
      return self.stream.getframerate() * self.bytes_per_frame()

  def load(self, in_fname):
      print 'load', self._mod.__name__, in_fname
      self.stream = self._mod.open(in_fname, 'rb')

  def read_lin(self):
      fragment = self.stream.readframes( self.stream.getnframes() )
      return self._conv(fragment, self.stream.getsampwidth())

  def init_from_template(self, out_fname, template_obj):
      print 'create', self._mod.__name__, out_fname
      self.stream = self._mod.open(out_fname, 'wb')
      self.stream.setnchannels( template_obj.stream.getnchannels() )
      self.stream.setsampwidth( template_obj.stream.getsampwidth() )
      self.stream.setframerate( template_obj.stream.getframerate() )

  def write_lin(self, fragment):
      self.stream.writeframes(self._conv(fragment, self.stream.getsampwidth()))

  def close(self):
      self.stream.close()


def coerce_lin(source_aiff, template_obj):
  '''Read data from source, and convert it to match template's params.'''
  import audioop
  frag = source_aiff.read_lin()
  Ss = source_aiff.stream
  St = template_obj.stream

  # Sample width
  if Ss.getsampwidth() != St.getsampwidth():
    print 'coerce sampwidth %i -> %i' %(Ss.getsampwidth(), St.getsampwidth())
    frag = audioop.lin2lin(frag, Ss.getsampwidth(), St.getsampwidth())
  width = St.getsampwidth()

  # Channels
  if Ss.getnchannels() != St.getnchannels():
    print 'coerce nchannels %i -> %i' %(Ss.getnchannels(), St.getnchannels())
    if Ss.getnchannels()==2 and St.getnchannels()==1:
      frag = audioop.tomono(frag, width, 0.5, 0.5)
    elif Ss.getnchannels()==1 and St.getnchannels()==2:
      frag = audioop.tostereo(frag, width, 1.0, 1.0)
    else:
      print "Err: can't match channels"

  # Frame rate
  if Ss.getframerate() != St.getframerate():
    print 'coerce framerate %i -> %i' %(Ss.getframerate(), St.getframerate())
    frag,state = audioop.ratecv(
        frag, width,
        St.getnchannels(),
        Ss.getframerate(), # in rate
        St.getframerate(), # out rate
        None, 2,1
      )
  return frag


def findfit(scratch_frag, final_frag, sound_file):
  '''Calculates the offset (in seconds) between scratch_frag & final_frag.
     Both fragments are assumed to contain the same, loud "clapper" event.
     The SoundFile object is used for common stream parameters.'''
  import audioop
  nchannels = sound_file.stream.getnchannels()
  framerate = sound_file.stream.getframerate()
  width = sound_file.stream.getsampwidth()
  assert(width==2)

  # Simplify the sound streams to make it quicker to find a match.
  # Left channel only.
  if nchannels > 1:
    scratch_frag_ = audioop.tomono(scratch_frag, width, 1, 0)
    final_frag_   = audioop.tomono(final_frag,   width, 1, 0)
  else:
    scratch_frag_ = scratch_frag
    final_frag_   = final_frag
  nchannels_ = 1

  # Downsample to 8000/sec
  framerate_ = 8000
  scratch_frag_,state =\
      audioop.ratecv(scratch_frag_, width, nchannels_, framerate, framerate_, None)
  final_frag_,state =\
      audioop.ratecv(final_frag_,   width, nchannels_, framerate, framerate_, None)
  bytes_per_second_ = nchannels_ * framerate_ * width

  # Find the clapper in final
  length_samples = int(0.001 * framerate * nchannels_) # 0.1 sec
  final_off_samples = audioop.findmax(final_frag_, length_samples)

  # Search for a 2 second 'needle' centred on where we found the 'clapper'
  needle_bytes = 2 * bytes_per_second_
  b0 = max(0, final_off_samples * width - int(needle_bytes/2))
  print '"clapper" at final:', 1.0*b0/bytes_per_second_, 'sec'
  b1 = b0 + needle_bytes
  final_clapper_frag = final_frag_[b0:b1]
  scratch_off_samples,factor = audioop.findfit(scratch_frag_, final_clapper_frag)
  scratch_off_bytes = scratch_off_samples * width
  print 'match at scratch:', 1.0*scratch_off_bytes/bytes_per_second_, 'sec', " factor =",factor

  # Calculate the offset (shift) between the two fragments.
  shift_sec = (scratch_off_bytes - b0) * 1.0 / bytes_per_second_
  print 'shift =', shift_sec, 'seconds'
  return shift_sec


def autoclapper(in_scratch_fname, in_final_fname, out_fname):
  """Read WAV- or AIFF-format files in_scratch_fname (a scratch audio track,
     taken from a video) & in_final_fname (a final-quality audio track of
     the same scene). Shift the 'final' stream to match the 'scratch' track,
     and write it out to out_fname. The result is a file that can be used
     directly as the video's sound-track."""

  # Read in the input streams.
  scratch = SoundFile( in_scratch_fname )
  final = SoundFile( in_final_fname )

  print 'scratch', scratch.stream.getparams()
  print 'final  ', final.stream.getparams()

  scratch_frag = coerce_lin(scratch, final)
  final_frag = final.read_lin()

  ## Shift final_frag to match scratch_frag
  shift_sec = findfit(scratch_frag, final_frag, final)
  shift_frames = int(shift_sec * final.stream.getframerate())
  shift_bytes = shift_frames * final.bytes_per_frame()

  print 'shift', shift_bytes, 'bytes'

  if shift_bytes > 0:
    final_frag = '\0' * shift_bytes + final_frag
  elif shift_bytes < 0:
    final_frag = final_frag[-shift_bytes:]

  ## Set final_frag length to match scratch_frag
  if len(final_frag) > len(scratch_frag):
    final_frag = final_frag[:len(scratch_frag)]
  elif len(final_frag) < len(scratch_frag):
    final_frag += '\0' * (len(scratch_frag) - len(final_frag))

  # Write out the result.
  sink = SoundFile( out_fname, final )
  sink.write_lin( final_frag )
  sink.close()


if __name__=='__main__':
  import sys

  if sys.argv[1] in ('-h', '--help', '-?'):
    print 'syntax: python autoclapper.py IN_SCRATCH_FNAME IN_FINAL_FNAME OUT_FNAME'
    print
    print autoclapper.__doc__
    print """
You can use "avconv" (or "ffmpeg") to extract audio tracks from video.
Example:

   $ avconv  -i raw_video.avi  scratch.wav
   $ python autoclapper.py  scratch.wav  raw_final.wav  synced_final.wav
   $ avconv  -i raw_video.avi  -i synced_final.wav  -map 0:0 -map 1:0  -codec copy  video.avi
"""

    sys.exit(0)

  in_scratch_fname = sys.argv[1]
  in_final_fname = sys.argv[2]
  out_fname = sys.argv[3]

  autoclapper(in_scratch_fname, in_final_fname, out_fname)
  
