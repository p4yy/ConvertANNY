"""Small deterministic detectors for pointer gestures used by the orbit."""
from collections import deque


class ShakeDetector:
    """Recognize repeated horizontal reversals inside a short rolling window."""
    def __init__(self,*,window=.8,minimum_turns=3,minimum_distance=40):
        self.window=float(window);self.minimum_turns=max(1,int(minimum_turns))
        self.minimum_distance=max(1,float(minimum_distance));self.samples=deque()

    def reset(self):self.samples.clear()

    def add(self,timestamp,x):
        now=float(timestamp);position=float(x)
        self.samples.append((now,position))
        while self.samples and now-self.samples[0][0]>self.window:self.samples.popleft()
        if len(self.samples)<2:return False
        anchor=self.samples[0][1];direction=0;turns=0
        for _,point in list(self.samples)[1:]:
            distance=point-anchor
            if abs(distance)>=self.minimum_distance:
                sign=1 if distance>0 else -1
                if direction and sign!=direction:turns+=1
                direction=sign;anchor=point
            elif direction and distance*direction>0:anchor=point
        return turns>=self.minimum_turns
