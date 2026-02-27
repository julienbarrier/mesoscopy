import qcodes.configuration as qcconfig

config: qcconfig.Config = qcconfig.Config()
from qcodes.logger.logger import conditionally_start_all_logging
conditionally_start_all_logging()
from qcodes import initialise_or_create_database_at as init_db
from qcodes import load_or_create_experiment as create_exp
import time
import numpy as np

__version__ = '0.2.0a'
