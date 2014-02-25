from setuptools import setup

setup(
    name='swift_image_scaler',
    version='2014.1',
    description='Swift middleware to scale images',
    long_description='',
    author='Bjoern Hagemeier',
    author_email='b.hagemeier@fz-juelich.de',
    packages=['swift_image_scaler'],
    install_requires=['setuptools'],
    entry_points="""
    [paste.filter_factory]
    image_scaler_filter = swift_image_scaler:image_scaler.filter_factory
    """
    )
