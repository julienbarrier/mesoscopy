from setuptools import setup, find_packages
from mesoscopy import __version__

setup(name='mesoscopy',
      version=__version__,
      description='Library of utils to run experiments in mesoscopic physics',
      url='https://github.com/julienbarrier/mesoscopy',
      author='Julien Barrier',
      author_email='julien@julienbarrier.eu',
      classifiers=[
          "Intended Audience :: Science/Research",
          "Programming Language :: Python :: 3 :: Only",
          "License :: MIT License",
          "Topic :: Scientific/Engineering",
      ],
      license='MIT',
      packages=find_packages(),
      python_requires=">=3.14",
      install_requires=[
          "matplotlib>=3.4.0",
          "pandas",
          "pyqt6",
          "numpy>=2.4.2",
          "qcodes>=0.55.0",
          "zhinst-qcodes",
          "qcodes_contrib_drivers>=0.24.0",
          "tqdm",
          "scipy",
          "pyserial"
      ],
      zip_safe=False)
