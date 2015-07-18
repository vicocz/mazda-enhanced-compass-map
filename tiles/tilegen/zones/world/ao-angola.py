#!/usr/bin/env python

# Tooling Template for Tile Generation
# DO NOT MODIFY 


from math import pi,cos,sin,log,exp,atan
from subprocess import call
import sys, os
from Queue import Queue
import threading
import mapnik

DEG_TO_RAD = pi/180
RAD_TO_DEG = 180/pi

# Default number of rendering threads to spawn, should be roughly equal to number of CPU cores available
NUM_THREADS = 6


def minmax (a,b,c):
    a = max(a,b)
    a = min(a,c)
    return a

class GoogleProjection:
    def __init__(self,levels=18):
        self.Bc = []
        self.Cc = []
        self.zc = []
        self.Ac = []
        c = 256
        for d in range(0,levels):
            e = c/2;
            self.Bc.append(c/360.0)
            self.Cc.append(c/(2 * pi))
            self.zc.append((e,e))
            self.Ac.append(c)
            c *= 2
                
    def fromLLtoPixel(self,ll,zoom):
         d = self.zc[zoom]
         e = round(d[0] + ll[0] * self.Bc[zoom])
         f = minmax(sin(DEG_TO_RAD * ll[1]),-0.9999,0.9999)
         g = round(d[1] + 0.5*log((1+f)/(1-f))*-self.Cc[zoom])
         return (e,g)
     
    def fromPixelToLL(self,px,zoom):
         e = self.zc[zoom]
         f = (px[0] - e[0])/self.Bc[zoom]
         g = (px[1] - e[1])/-self.Cc[zoom]
         h = RAD_TO_DEG * ( 2 * atan(exp(g)) - 0.5 * pi)
         return (f,h)



class RenderThread:
    def __init__(self, tile_dir, mapfile, q, printLock, maxZoom):
        self.tile_dir = tile_dir
        self.q = q
        self.m = mapnik.Map(256, 256)
        self.printLock = printLock
        # Load style XML
        mapnik.load_map(self.m, mapfile, True)
        # Obtain <Map> projection
        self.prj = mapnik.Projection(self.m.srs)
        # Projects between tile pixel co-ordinates and LatLong (EPSG:4326)
        self.tileproj = GoogleProjection(maxZoom+1)


    def render_tile(self, tile_uri, x, y, z):

        # Calculate pixel positions of bottom-left & top-right
        p0 = (x * 256, (y + 1) * 256)
        p1 = ((x + 1) * 256, y * 256)

        # Convert to LatLong (EPSG:4326)
        l0 = self.tileproj.fromPixelToLL(p0, z);
        l1 = self.tileproj.fromPixelToLL(p1, z);

        # Convert to map projection (e.g. mercator co-ords EPSG:900913)
        c0 = self.prj.forward(mapnik.Coord(l0[0],l0[1]))
        c1 = self.prj.forward(mapnik.Coord(l1[0],l1[1]))

        # Bounding box for the tile
        if hasattr(mapnik,'mapnik_version') and mapnik.mapnik_version() >= 800:
            bbox = mapnik.Box2d(c0.x,c0.y, c1.x,c1.y)
        else:
            bbox = mapnik.Envelope(c0.x,c0.y, c1.x,c1.y)
        render_size = 256
        self.m.resize(render_size, render_size)
        self.m.zoom_to_box(bbox)
        if(self.m.buffer_size < 128):
            self.m.buffer_size = 128

        # Render image with default Agg renderer
        im = mapnik.Image(render_size, render_size)
        mapnik.render(self.m, im)
        im.save(tile_uri, 'png256')


    def loop(self):
        while True:
            #Fetch a tile from the queue and render it
            r = self.q.get()
            if (r == None):
                self.q.task_done()
                break
            else:
                (name, tile_uri, x, y, z) = r

            exists= ""
            if os.path.isfile(tile_uri):
                exists= "exists"
            else:
                self.render_tile(tile_uri, x, y, z)
            bytes=os.stat(tile_uri)[6]
            empty= ''

            if bytes == 103:
                empty = " Empty Tile "
                os.remove(tile_uri)

            self.printLock.acquire()
            print name, ":", z, x, y, exists, empty
            self.printLock.release()
            self.q.task_done()



def render_tiles(bbox, mapfile, tile_dir, minZoom=1,maxZoom=18, name="unknown", num_threads=NUM_THREADS, tms_scheme=False):
    print "render_tiles(",bbox, mapfile, tile_dir, minZoom,maxZoom, name,")"

    tile_dir = tile_dir + name + "/";

    # Launch rendering threads
    queue = Queue(32)
    printLock = threading.Lock()
    renderers = {}
    for i in range(num_threads):
        renderer = RenderThread(tile_dir, mapfile, queue, printLock, maxZoom)
        render_thread = threading.Thread(target=renderer.loop)
        render_thread.start()
        #print "Started render thread %s" % render_thread.getName()
        renderers[i] = render_thread

    if not os.path.exists(tile_dir):
         os.makedirs(tile_dir)

    gprj = GoogleProjection(maxZoom+1) 

    ll0 = (bbox[0],bbox[3])
    ll1 = (bbox[2],bbox[1])

    for z in range(minZoom,maxZoom + 1):
        px0 = gprj.fromLLtoPixel(ll0,z)
        px1 = gprj.fromLLtoPixel(ll1,z)

        # check if we have directories in place
        zoom = "%s" % z
        if not os.path.isdir(tile_dir + zoom):
            os.mkdir(tile_dir + zoom)
        for x in range(int(px0[0]/256.0),int(px1[0]/256.0)+1):
            # Validate x co-ordinate
            if (x < 0) or (x >= 2**z):
                continue
            # check if we have directories in place
            str_x = "%s" % x
            if not os.path.isdir(tile_dir + zoom + '/' + str_x):
                os.mkdir(tile_dir + zoom + '/' + str_x)
            for y in range(int(px0[1]/256.0),int(px1[1]/256.0)+1):
                # Validate x co-ordinate
                if (y < 0) or (y >= 2**z):
                    continue
                # flip y to match OSGEO TMS spec
                if tms_scheme:
                    str_y = "%s" % ((2**z-1) - y)
                else:
                    str_y = "%s" % y
                tile_uri = tile_dir + zoom + '/' + str_x + '/' + str_y + '.png'
                # Submit tile to be rendered into the queue
                t = (name, tile_uri, x, y, z)
                try:
                    queue.put(t)
                except KeyboardInterrupt:
                    raise SystemExit("Ctrl-c detected, exiting...")

    # Signal render threads to exit by sending empty request to queue
    for i in range(num_threads):
        queue.put(None)
    # wait for pending rendering jobs to complete
    queue.join()
    for i in range(num_threads):
        renderers[i].join()




if __name__ == "__main__":
    home = os.environ['HOME']
    try:
        mapfile = "../tilestyles/mazda/mazda.xml"
    except KeyError:
        print("[MapFile] Not found")
        sys.exit(1)
    try:
        # ./tilegen/zones/[zone]/[region]
        tile_dir = "../../../output/"
    except KeyError:
        print("[OutputDir] No output directory found")
        sys.exit(1)

    if not tile_dir.endswith('/'):
        tile_dir = tile_dir + '/'


    # ------------------------------------------------------------------------
    # Tile Render Data
    # Zone: world
    # Region: AO
    # Region Name: Angola

	render_tiles((12.20966,-5.77091,12.28389,-5.73445), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.28389,-5.73445,12.52666,-5.72417), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.52666,-5.72417,12.28389,-5.73445), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.155,-5.68167,12.52666,-5.72417), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.15416,-5.60528,12.17805,-5.54139), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.17805,-5.54139,12.22389,-5.53472), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.22389,-5.53472,12.17805,-5.54139), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.22861,-5.47694,12.22389,-5.53472), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.105,-5.16694,12.53889,-5.12083), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.53889,-5.12083,12.46205,-5.09236), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.46205,-5.09236,12.53889,-5.12083), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.06666,-5.04972,12.01972,-5.04528), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.01972,-5.04528,12.06666,-5.04972), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.04583,-5.02834,12.01007,-5.02062), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.01007,-5.02062,12.11444,-5.01528), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.01007,-5.02062,12.11444,-5.01528), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.11444,-5.01528,12.01007,-5.02062), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.70805,-4.91861,12.16639,-4.89583), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.16639,-4.89583,12.70805,-4.91861), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.29222,-4.79361,12.20638,-4.75889), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.20638,-4.75889,12.82555,-4.73556), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.82555,-4.73556,12.20638,-4.75889), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.0825,-4.67,13.09105,-4.63307), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.09105,-4.63307,12.41278,-4.6025), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.41278,-4.6025,13.09105,-4.63307), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.65,-4.55944,12.66444,-4.52167), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.66444,-4.52167,12.92222,-4.48528), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.92222,-4.48528,12.66444,-4.52167), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.89583,-4.41528,12.78083,-4.38889), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.78083,-4.38889,12.89583,-4.41528), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((20.78486,-18.01173,21.4236,-18.00667), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((21.38264,-18.01173,21.4236,-18.00667), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((21.4236,-18.00667,20.78486,-18.01173), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((20.97166,-17.9625,21.24277,-17.93834), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((21.24277,-17.93834,20.97166,-17.9625), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((19.75555,-17.8975,20.09972,-17.89556), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((20.09972,-17.89556,19.75555,-17.8975), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((20.3936,-17.8875,20.09972,-17.89556), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((19.45971,-17.86167,19.91527,-17.85751), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((19.91527,-17.85751,19.45971,-17.86167), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((19.66249,-17.83723,19.91527,-17.85751), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((18.91666,-17.81501,19.66249,-17.83723), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((22.83777,-17.74722,18.71971,-17.70695), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((18.71971,-17.70695,22.83777,-17.74722), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((23.47486,-17.62453,18.71971,-17.70695), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((23.20166,-17.47972,18.48333,-17.44028), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((18.48333,-17.44028,13.98083,-17.425), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.98083,-17.425,14.18777,-17.41639), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((14.18777,-17.41639,13.98083,-17.425), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((17.0225,-17.39194,15.62611,-17.38889), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((15.62611,-17.38889,14.21805,-17.38695), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((14.21805,-17.38695,18.40734,-17.38678), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((18.40734,-17.38678,14.21805,-17.38695), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((14.20931,-17.38678,14.21805,-17.38695), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((11.75375,-17.25786,12.45166,-17.25362), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.45166,-17.25362,11.75375,-17.25786), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.50861,-17.23889,12.24694,-17.22667), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.24694,-17.22667,12.50861,-17.23889), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((11.75582,-17.20619,12.42833,-17.20556), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.42833,-17.20556,11.75582,-17.20619), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((11.97694,-17.16361,12.12305,-17.14834), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.12305,-17.14834,13.54472,-17.13667), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.54472,-17.13667,12.12305,-17.14834), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.49694,-17.02695,12.93888,-17.01139), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.93888,-17.01139,13.49694,-17.02695), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.37416,-16.96889,12.93888,-17.01139), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((11.76944,-16.82751,11.815,-16.80251), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((11.815,-16.80251,11.76944,-16.82751), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((22.24888,-16.57,22.13888,-16.4925), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((22.13888,-16.4925,22.24888,-16.57), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((22.07083,-16.23917,11.78611,-16.18334), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((11.78611,-16.18334,22.00079,-16.17085), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((22.00079,-16.17085,11.78611,-16.18334), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((11.80833,-15.98195,11.73111,-15.85472), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((11.73111,-15.85472,11.74139,-15.81972), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((11.74139,-15.81972,11.86333,-15.78473), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((11.86333,-15.78473,11.78055,-15.77861), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((11.78055,-15.77861,11.86333,-15.78473), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.015,-15.56945,11.78055,-15.77861), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.06472,-15.21194,12.14611,-15.17334), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.14611,-15.17334,12.06472,-15.21194), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((21.99944,-14.52111,12.34167,-14.39084), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.34167,-14.39084,21.99944,-14.52111), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.31722,-14.18084,12.34167,-14.39084), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.41278,-13.88084,12.48917,-13.87973), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.48917,-13.87973,12.41278,-13.88084), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.50583,-13.83834,12.48917,-13.87973), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.51555,-13.41722,12.64055,-13.33945), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.64055,-13.33945,12.63416,-13.29195), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.63416,-13.29195,21.99853,-13.2535), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((21.99853,-13.2535,12.72944,-13.21778), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.72944,-13.21778,21.99853,-13.2535), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((24.02055,-13.00639,23.33166,-13.00584), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((23.33166,-13.00584,24.02055,-13.00639), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((22.64416,-13.00528,23.33166,-13.00584), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((21.99833,-13.00417,22.64416,-13.00528), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((24.01694,-12.98722,21.99833,-13.00417), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.96639,-12.9525,24.01694,-12.98722), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.92555,-12.83806,23.88694,-12.80472), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((23.88694,-12.80472,12.98889,-12.77195), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.98889,-12.77195,23.88694,-12.80472), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((23.91499,-12.66972,13.34889,-12.60472), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.34889,-12.60472,13.19222,-12.59861), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.19222,-12.59861,13.34889,-12.60472), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.38305,-12.58334,13.19222,-12.59861), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((24.05222,-12.38528,13.51388,-12.36417), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.51388,-12.36417,24.05222,-12.38528), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.59416,-12.31056,24.03499,-12.26417), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((24.03499,-12.26417,13.59416,-12.31056), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((23.97499,-12.2,24.03499,-12.26417), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.77417,-11.88334,23.99554,-11.77167), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((23.99554,-11.77167,13.77417,-11.88334), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.78139,-11.49834,24.02861,-11.45778), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((24.02861,-11.45778,24.06221,-11.42195), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((24.06221,-11.42195,24.02861,-11.45778), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.82139,-11.29583,22.24446,-11.25064), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((22.24446,-11.25064,13.82139,-11.29583), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((22.4836,-11.13,22.94277,-11.095), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((22.94277,-11.095,22.7236,-11.09333), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((22.7236,-11.09333,23.10805,-11.09195), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((23.10805,-11.09195,22.7236,-11.09333), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((22.2461,-11.07306,23.10805,-11.09195), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((22.86916,-11.05056,22.51971,-11.04195), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((22.51971,-11.04195,22.58083,-11.03445), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((22.58083,-11.03445,23.85055,-11.02778), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((23.85055,-11.02778,22.58083,-11.03445), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((23.8861,-11.01472,23.85055,-11.02778), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((23.39749,-10.97028,23.50305,-10.95972), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((23.50305,-10.95972,13.84805,-10.95056), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.84805,-10.95056,23.50305,-10.95972), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((22.16555,-10.87333,23.98272,-10.86963), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((23.98272,-10.86963,22.16555,-10.87333), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((22.18666,-10.82917,23.98272,-10.86963), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((22.31305,-10.76722,13.72389,-10.75889), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.72389,-10.75889,22.31305,-10.76722), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.77333,-10.69723,13.76472,-10.66611), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.76472,-10.66611,13.77333,-10.69723), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((22.30333,-10.53778,22.26416,-10.50056), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((22.26416,-10.50056,22.30333,-10.53778), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.52583,-10.40556,22.31444,-10.38584), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((22.31444,-10.38584,13.52583,-10.40556), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.52111,-10.32111,22.31444,-10.38584), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.36444,-10.05611,22.14721,-9.91139), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((22.14721,-9.91139,13.32722,-9.90139), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.32722,-9.90139,22.14721,-9.91139), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((22.02499,-9.85139,13.32722,-9.90139), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.18944,-9.68723,13.22416,-9.61611), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.22416,-9.61611,13.18944,-9.68723), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((21.83499,-9.53361,13.22416,-9.61611), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((21.79055,-9.40556,13.14312,-9.33659), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.14312,-9.33659,21.79055,-9.40556), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((21.85471,-9.22945,13.14312,-9.33659), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.01861,-9.08639,12.98472,-9.075), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.98472,-9.075,13.01861,-9.08639), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.00055,-9.05473,12.98472,-9.075), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.01889,-8.98361,13.00055,-9.05473), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.13778,-8.87222,21.86027,-8.85472), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((21.86027,-8.85472,13.13778,-8.87222), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.24027,-8.79806,13.2175,-8.78278), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.2175,-8.78278,13.36028,-8.76834), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.36028,-8.76834,13.2175,-8.78278), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.3875,-8.74028,13.36028,-8.76834), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.40861,-8.65333,13.3875,-8.74028), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.345,-8.46972,13.38166,-8.45084), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.38166,-8.45084,21.93721,-8.44306), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((21.93721,-8.44306,13.38166,-8.45084), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.37389,-8.33695,21.93721,-8.44306), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((18.00722,-8.10806,18.11805,-8.10694), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((18.11805,-8.10694,18.00722,-8.10806), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((17.63805,-8.09805,18.11805,-8.10694), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((17.80499,-8.08639,18.11194,-8.07806), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((18.11194,-8.07806,17.53722,-8.07722), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((17.53722,-8.07722,18.11194,-8.07806), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((21.80916,-8.06222,17.74055,-8.06195), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((17.74055,-8.06195,21.80916,-8.06222), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((17.92221,-8.04667,17.8686,-8.04583), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((17.8686,-8.04583,17.92221,-8.04667), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((17.54333,-8.02139,18.13527,-8.02083), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((18.13527,-8.02083,17.54333,-8.02139), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((18.79499,-7.99889,19.37305,-7.99611), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((19.37305,-7.99611,18.52583,-7.99556), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((18.52583,-7.99556,19.37305,-7.99611), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((21.74944,-7.945,18.76777,-7.93055), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((18.76777,-7.93055,18.53111,-7.93028), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((18.53111,-7.93028,18.76777,-7.93055), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((17.43721,-7.92472,18.53111,-7.93028), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.12389,-7.86806,19.35916,-7.85806), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((19.35916,-7.85806,13.12389,-7.86806), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((17.41972,-7.84806,19.35916,-7.85806), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((17.28416,-7.69944,17.28777,-7.62639), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((17.28777,-7.62639,17.21444,-7.58861), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((17.21444,-7.58861,19.37749,-7.57167), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((19.37749,-7.57167,19.47138,-7.56861), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((19.47138,-7.56861,19.37749,-7.57167), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((17.14666,-7.46945,19.53583,-7.46), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((19.53583,-7.46,21.8461,-7.4525), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((21.8461,-7.4525,19.53583,-7.46), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((17.1811,-7.42778,17.10555,-7.42222), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((17.10555,-7.42222,17.1811,-7.42778), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((19.49944,-7.35167,21.81971,-7.32556), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((21.81971,-7.32556,17.02527,-7.30833), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((17.02527,-7.30833,21.81971,-7.32556), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((20.54193,-7.28468,21.10305,-7.28278), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((21.10305,-7.28278,21.7836,-7.28167), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((21.7836,-7.28167,21.10305,-7.28278), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((16.94582,-7.20833,12.84305,-7.17334), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.84305,-7.17334,19.50471,-7.14389), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((19.50471,-7.14389,20.53999,-7.14222), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((20.53999,-7.14222,19.50471,-7.14389), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((19.56638,-7.05306,16.96082,-7.03889), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((16.96082,-7.03889,19.56638,-7.05306), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((19.54222,-6.99722,19.63111,-6.99694), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((19.63111,-6.99694,19.54222,-6.99722), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((20.31138,-6.99472,19.63111,-6.99694), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((16.96,-6.98528,20.31138,-6.99472), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((16.92722,-6.9175,20.6311,-6.91444), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((20.6311,-6.91444,12.83472,-6.91361), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((20.33249,-6.91444,12.83472,-6.91361), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.83472,-6.91361,20.6311,-6.91444), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((16.91194,-6.86556,12.83472,-6.91361), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((16.84111,-6.79944,16.91194,-6.86556), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.62277,-6.72611,16.84111,-6.79944), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.51889,-6.58194,16.70388,-6.46445), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((16.70388,-6.46445,12.51889,-6.58194), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((16.71749,-6.17722,12.28389,-6.12194), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.28389,-6.12194,12.2475,-6.10917), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.2475,-6.10917,12.28389,-6.12194), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.25416,-6.07833,12.31083,-6.05528), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.31083,-6.05528,12.25416,-6.07833), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((16.6,-6.0125,12.83139,-6.005), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.83139,-6.005,16.6,-6.0125), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((16.57972,-5.90083,13.0975,-5.89778), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.0975,-5.89778,16.57972,-5.90083), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((14.33555,-5.8925,13.34139,-5.89056), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.34139,-5.89056,14.33555,-5.8925), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((12.985,-5.88278,13.34139,-5.89056), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((15.02806,-5.86278,13.17802,-5.85961), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.17802,-5.85961,15.70527,-5.85861), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.17802,-5.85961,15.70527,-5.85861), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((15.70527,-5.85861,13.17802,-5.85961), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.50083,-5.85528,13.40805,-5.85389), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.40805,-5.85389,16.36832,-5.85306), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((16.36832,-5.85306,13.40805,-5.85389), mapfile, tile_dir, 0, 11, "ao-angola")
	render_tiles((13.98028,-5.83583,16.36832,-5.85306), mapfile, tile_dir, 0, 11, "ao-angola")