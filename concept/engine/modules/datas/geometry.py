from typing import List


class Point:
    pass

class Curve:
    '''подразумевается, что первая точка - начало, последняя - конец'''
    listPoints: List[Point]
    pass

class ClosedCurve:
    '''подразумевается, что первая точка - начало и конец одновременно.
    Думаю, так лучше организовать для алгоритмов'''
    listPoints: List[Point]
    pass