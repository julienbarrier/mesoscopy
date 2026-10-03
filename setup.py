import re
from setuptools import setup, find_packages

with open("mesoscopy/__init__.py") as f:
    match = re.search(r"^__version__\s*=\s*['\"]([^'\"]+)['\"]", f.read(), re.M)
    if not match:
        raise RuntimeError("Unable to find __version__ in mesoscopy/__init__.py")
    __version__ = match.group(1)

setup(name='mesoscopy',
      version=__version__,
      description='Graphical interface to run experiments',
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
          "matplotlib>=3.8",
          "numpy>=2.4.2",
          "pyqt6>=6.10.2",
          "pyyaml",
          "qcodes>=0.60.0",
          "scipy",
      ],
      extras_require={
          # drivers that the station files of some setups use
          "zurich": ["zhinst>=26.7.2", "zhinst-qcodes>=0.8.1", "qcodes_contrib_drivers>=0.24.0"],
          "visa": ["pyvisa-py", "pyserial"],
      },
      entry_points={
          "console_scripts": [
              "mesoscopy=mesoscopy.main:main",
          ],
      },
      zip_safe=False)
