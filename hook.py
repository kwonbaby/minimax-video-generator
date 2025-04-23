# Runtime hook to ensure correct loading order
import os
import sys
import numpy  # Load numpy before pandas to avoid compatibility issues
