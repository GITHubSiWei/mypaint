# This file is part of MyPaint.
# Copyright (C) 2008 by Martin Renold <martinxyz@gmx.ch>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License.
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY. See the COPYING file for more details.

import mypaintlib, tilelib, brush
import gtk, numpy, cairo
gdk = gtk.gdk
from math import floor, ceil
import time

class TiledDrawWidget(gtk.DrawingArea):
    def __init__(self):
        gtk.DrawingArea.__init__(self)
        self.connect("proximity-in-event", self.proximity_cb)
        self.connect("proximity-out-event", self.proximity_cb)
        self.toolchange_observers = []

        self.connect("motion-notify-event", self.motion_notify_cb)
        #self.connect("button-press-event", self.button_updown_cb)
        #self.connect("button-release-event", self.button_updown_cb)
        self.connect("expose-event", self.expose_cb)
        self.connect("enter-notify-event", self.enter_notify_cb)
        self.connect("leave-notify-event", self.leave_notify_cb)

        self.set_events(gdk.EXPOSURE_MASK
                        | gdk.ENTER_NOTIFY_MASK
                        | gdk.LEAVE_NOTIFY_MASK
                        | gdk.BUTTON_PRESS_MASK
                        | gdk.BUTTON_RELEASE_MASK
                        | gdk.POINTER_MOTION_MASK
                        | gdk.PROXIMITY_IN_MASK
                        | gdk.PROXIMITY_OUT_MASK
                        )

        self.set_extension_events (gdk.EXTENSION_EVENTS_ALL)

        self.brush = None
        self.layer = None # tilelib.TiledLayer()
        self.displayed_layers = None # tilelib.TiledLayer()

        self.last_event_time = None
        self.last_event_x = None
        self.last_event_y = None

        self.recording = None

        self.disableGammaCorrection = False

        self.translation_x = 0.0
        self.translation_y = 0.0
        self.scale = 1.0
        self.rotation = 0.0
        self.viewport_locked = False

        self.has_pointer = False
        self.dragfunc = None

    def proximity_cb(self, widget, something):
        for f in self.toolchange_observers:
            f()

    def enter_notify_cb(self, widget, event):
        self.has_pointer = True
    def leave_notify_cb(self, widget, event):
        self.has_pointer = False

    def motion_notify_cb(self, widget, event):
        if self.last_event_time:
            dtime = (event.time - self.last_event_time)/1000.0
            dx = event.x - self.last_event_x
            dy = event.y - self.last_event_y
        else:
            dtime = None
        self.last_event_time = event.time
        self.last_event_x = event.x
        self.last_event_y = event.y
        if dtime is None:
            return

        if self.dragfunc:
            self.dragfunc(dx, dy)
            return

        cr = self.get_model_coordinates_cairo_context()
        x, y = cr.device_to_user(event.x, event.y)
        
        pressure = event.get_axis(gdk.AXIS_PRESSURE)
        if pressure is None:
            if event.state & gdk.BUTTON1_MASK:
                pressure = 0.5
            else:
                pressure = 0.0

        if not self.brush:
            print 'no brush!'
            return
        # FIXME: we should have a "model" object from which we fetch the current layer
        assert isinstance(self.layer, tilelib.TiledLayer)

        if self.recording is not None:
            self.recording.append((dtime, x, y, pressure))
        bbox = self.brush.tiled_surface_stroke_to (self.layer, x, y, pressure, dtime)
        if bbox:
            # TODO: we should accumulate dirty regions and bboxes, and
            #       do the stuff below once per redraw, not once per event
            #       Question: who keeps bboxes and dirty tile list between event?
            x1, y1, w, h = bbox
            x2 = x1 + w - 1
            y2 = y1 + h - 1
            # transform 4 bbox corners to screen coordinates
            corners = [(x1, y1), (x1+w-1, y1), (x1, y1+h-1), (x1+w-1, y1+h-1)]
            corners = [cr.user_to_device(x, y) for (x, y) in corners]
            # find screen bbox containing the old (rotated, translated) rectangle
            list_y = [y for (x, y) in corners]
            list_x = [x for (x, y) in corners]
            x1 = int(floor(min(list_x)))
            y1 = int(floor(min(list_y)))
            x2 = int(ceil(max(list_x)))
            y2 = int(ceil(max(list_y)))
            self.queue_draw_area(x1, y1, x2-x1+1, y2-y1+1)

    def expose_cb(self, widget, event):
        t = time.time()
        if hasattr(self, 'last_expose_time'):
            # just for basic performance comparisons... but we could sleep if we make >50fps
            print '%d fps' % int(1.0/(t-self.last_expose_time))
        self.last_expose_time = t
        print 'expose', tuple(event.area)

        self.repaint()

    def get_model_coordinates_cairo_context(self):
        cr = self.window.cairo_create()
        cr.translate(self.translation_x, self.translation_y)
        cr.rotate(self.rotation)
        cr.scale(self.scale, self.scale)
        self.last_cairo_context = cr
        return cr

    def repaint(self):
        cr = self.get_model_coordinates_cairo_context()
        #cr.rectangle(*event.area)
        #cr.clip()

        w, h = self.window.get_size()
        pixbuf = gdk.Pixbuf(gdk.COLORSPACE_RGB, False, 8, w, h)

        pixbuf.fill(0xffffffff)
        arr = pixbuf.get_pixels_array()
        arr = mypaintlib.gdkpixbuf2numpy(arr)

        #if not self.disableGammaCorrection:
        #    for surface in self.displayed_layers:
        #        surface.compositeOverWhiteRGB8(arr)
        #else:
        for surface in self.displayed_layers:
            surface.compositeOverRGB8(arr)

        #widget.window.draw_pixbuf(None, pixbuf, 0, 0, 0, 0)
        #cr.rectangle(0,0,w,h)
        #cr.clip()
        cr.set_source_pixbuf(pixbuf, 0, 0)
        cr.paint()

    def clear(self):
        print 'TODO: clear'

    def lock_viewport(self, lock=True):
        self.viewport_locked = lock

    def scroll(self, dx, dy):
        if self.viewport_locked:
            return
        self.translation_x -= dx
        self.translation_y -= dy
        print 'TODO: fast scrolling without so much rerendering'
        # and TODO: scroll with spacebar, with mouse, ...
        self.queue_draw()

    def rotozoom_with_center(self, function):
        if self.viewport_locked:
            return
        if self.has_pointer and self.last_event_x is not None:
            cx, cy = self.last_event_x, self.last_event_y
        else:
            w, h = self.window.get_size()
            cx, cy = w/2.0, h/2.0
        cr = self.get_model_coordinates_cairo_context()
        cx_device, cy_device = cr.device_to_user(cx, cy)
        function()
        cr = self.get_model_coordinates_cairo_context()
        cx_new, cy_new = cr.user_to_device(cx_device, cy_device)
        self.translation_x += cx - cx_new
        self.translation_y += cy - cy_new
        self.queue_draw()

    def zoom(self, zoom_step):
        def f(): self.scale *= zoom_step
        self.rotozoom_with_center(f)

    def set_zoom(self, zoom):
        def f(): self.scale = zoom
        self.rotozoom_with_center(f)

    def rotate(self, angle_step):
        def f(): self.rotation += angle_step
        self.rotozoom_with_center(f)

    def set_rotation(self, angle):
        def f(): self.rotation = angle
        self.rotozoom_with_center(f)


    def start_drag(self, dragfunc):
        self.dragfunc = dragfunc
    def stop_drag(self, dragfunc):
        if self.dragfunc == dragfunc:
            self.dragfunc = None

    def set_brush(self, b):
        self.brush = b


    def start_recording(self):
        assert self.recording is None
        self.recording = []

    def stop_recording(self):
        # OPTIMIZE 
        # - for space: just gzip? use integer datatypes?
        # - for time: maybe already use array storage while recording?
        data = numpy.array(self.recording, dtype='float64').tostring()
        version = '2'
        self.recording = None
        return version + data

    def playback(self, data):
        version, data = data[0], data[1:]
        assert version == '2'
        for dtime, x, y, pressure in numpy.fromstring(data, dtype='float64'):
            self.brush.tiled_surface_stroke_to (self.layer, x, y, pressure, dtime)

