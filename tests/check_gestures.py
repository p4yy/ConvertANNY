"""Check the timing, distance and reversal requirements of the shake detector."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from convertanny_core.gestures import ShakeDetector


def check():
    detector=ShakeDetector()
    motion=[(0,0),(.1,50),(.2,0),(.3,50),(.4,0),(.5,50),(.6,0)]
    assert not any(detector.add(*sample) for sample in motion[:4])
    assert detector.add(*motion[4])
    detector.reset()
    assert not any(detector.add(*sample) for sample in [(0,0),(.1,20),(.2,0),(.3,20),(.4,0),(.5,20)])
    detector.reset()
    assert not any(detector.add(*sample) for sample in [(0,0),(.1,50),(1,0),(1.1,50),(1.2,0),(1.3,50)])
    detector.reset()
    assert detector.add(0,0) is False and detector.add(.1,50) is False
    print('Shake gesture thresholds and time window passed')


if __name__=='__main__':check()
