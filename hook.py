# Runtime hook to ensure correct loading order and version compatibility
import os
import sys
import logging

# Set up logging to troubleshoot
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='minimax_app.log'
)

try:
    import numpy
    logging.info(f"NumPy loaded successfully: version {numpy.__version__}")
except Exception as e:
    logging.error(f"Error loading NumPy: {e}")

try:
    import pandas
    logging.info(f"Pandas loaded successfully: version {pandas.__version__}")
except Exception as e:
    logging.error(f"Error loading Pandas: {e}")
