
class Limits:
    def __init__(self, max_total_points=100000, max_slices=1000, max_operations=100, max_points_per_contour=10000):
        self.max_total_points = max_total_points
        self.max_slices = max_slices
        self.max_operations = max_operations
        self.max_points_per_contour = max_points_per_contour
