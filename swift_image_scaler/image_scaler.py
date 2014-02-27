###########################################################################
# Copyright (c) 2014 Forschungszentrum Juelich GmbH 
# All rights reserved.

# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:

# (1) Redistributions of source code must retain the above copyright notice,
# this list of conditions and the disclaimer at the end. Redistributions in
# binary form must reproduce the above copyright notice, this list of
# conditions and the following disclaimer in the documentation and/or other
# materials provided with the distribution.

# (2) Neither the name of Forschungszentrum Juelich GmbH nor the names of its 
# contributors may be used to endorse or promote products derived from this 
# software without specific prior written permission.

# DISCLAIMER

# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
###########################################################################

from PythonMagick import Image, Blob

from swift.common.utils import get_logger
from swift.proxy.controllers.base import get_container_info, get_object_info
from swift.common.swob import Request, Response

from paste.response import header_value, remove_header
from paste.httpheaders import CONTENT_LENGTH

from StringIO import StringIO

from urllib import splitquery
from urlparse import parse_qs

class ImageScalerMiddleware(object):
    """
    Scale images through this middleware.

    The ultimate goal is to make this scaling permanent, i.e. write back a scaled
    version of an image to the object store, such that it is available again for
    a later request.

    This requires a number of settings:

    enable-scaling: on the container
    writeback-scaling: container

    Scaled versions that have been written back can only be used directly
    if their timestamp is newer than the timestamp of the original image.
    """

    def __init__(self, app, conf, logger=None):
        self.app = app
        if logger:
            self.logger = logger
        else:
            self.logger = get_logger(conf, log_route='image-scaler')

    def __call__(self, env, start_response):
        req = Request(env)

        try:
            version, account, container, obj = req.split_path(1, 4, True)
        except ValueError:
            return self.app(env, start_response)

        container_info = get_container_info(
            req.environ, self.app, swift_source='ImageScalerMiddleware')

        # parse query string
        if req.query_string:
            qs = parse_qs(req.query_string)
            if 'size' in qs:
                req_size = qs['size']
            else:
                self.logger.debug("image-scaler: No image scaling requested.")
                return self.app(env, start_response)
        else:
            # nothing for us to do, no scaling requested
            self.logger.debug("image-scaler: No image scaling requested.")
            return self.app(env, start_response)

        # check container whether scaling is allowed
        meta = container_info['meta']
        if not meta.has_key('image-scaling') or \
                meta.has_key('image-scaling') and \
                not meta['image-scaling'].lower() in ['true', '1']:
            # nothing for us to do
            self.logger.debug("image-scaler: Image scaling not "
                             "allowed. Nothing for us to do.")
            return self.app(env, start_response)

        # default allowed extensions
        allowed_exts = ['jpg','png','gif']
        # check whether file has the allowed ending
        if meta.has_key('image-scaling-extensions'):
            allowed_exts = meta['image-scaling-extensions'].split(',')

        requested_ext = req.path.rsplit('.', 1)[-1]
        if not requested_ext.lower() in map(lambda x: x.lower(), allowed_exts):
            self.logger.info("image-scaler: extension %s not allowed"
                              " for image scaling" % requested_ext)
            return self.app(env, start_response)

        # 20MB
        max_size = 20971520
        if meta.has_key('image-scaling-max-size'):
            max_size = int(meta['image-scaling-max-size'])
        obj_info = get_object_info(req.environ, self.app, swift_source="ImageScalerMiddleware")
        if int(obj_info['length']) > max_size:
            self.logger.info("image-scaler: object too large")
            return self.app(env, start_response)

        response = ImageScalerResponse(start_response, req_size, self.logger)
        app_iter = self.app(env, response.scaler_start_response)

        if app_iter is not None:
            response.finish_response(app_iter)

        return response.write()

class ImageScalerResponse(object):
    
    def __init__(self, start_response, scaled_size, logger):
        self.start_response = start_response
        self.scaled_size = scaled_size
        self.outbuffer = Blob()
        self.content_length = None
        self.logger = logger

    def scaler_start_response(self, status, headers, exc_info=None):
        remove_header(headers, 'content-length')
        self.headers = headers
        self.status = status
        return self.outbuffer.data

    def write(self):
        return [self.outbuffer.data]

    def finish_response(self, app_iter):
        inBuffer = StringIO()
        try:
            for s in app_iter:
                self.logger.debug("Writing %d bytes into image buffer." % len(s))
                inBuffer.write(s)
        finally:
            if hasattr(app_iter, 'close'):
                app_iter.close()

        rawImg = Blob()
        rawImg.data = inBuffer.getvalue()
        inBuffer.close()
        image = Image(rawImg)
        self.logger.debug("Scaling image to %s" % self.scaled_size)
        image.scale(self.scaled_size[0])
        image.write(self.outbuffer)

        content_length = self.outbuffer.length()
        CONTENT_LENGTH.update(self.headers, content_length)
        self.start_response(self.status, self.headers)

def scale_image(data, size):
    image = Image(data)
    image.scale(size)
    rawImage = Blob()
    image.write(rawImage)
    return [rawImage]


def filter_factory(global_conf, **local_conf):
    """
    """
    conf = global_conf.copy()
    conf.update(local_conf)

    def image_scaler(app):
        return ImageScalerMiddleware(app, conf)
    return image_scaler
