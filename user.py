#!/usr/bin/env python
from __future__ import print_function
from yapsy.PluginManager import PluginManager
import argparse  # new in Python2.7
import atexit
import logging
import string
import sys
import threading
import time

logging.basicConfig(level=logging.ERROR)

# Load the plugins from the plugin directory.
manager = PluginManager()

if __name__ == '__main__':

    print("------------user.py-------------")
    parser = argparse.ArgumentParser(description="OpenBCI 'user'")
    parser.add_argument('--board', default="cyton",
                        help="Choose between [cyton] and [ganglion] boards.")
    parser.add_argument('-l', '--list', action='store_true',
                        help="List available plugins.")
    parser.add_argument('-i', '--info', metavar='PLUGIN',
                        help="Show more information about a plugin.")
    parser.add_argument('-p', '--port',
                        help="For Cyton, port to connect to OpenBCI Dongle " +
                             "( ex /dev/ttyUSB0 or /dev/tty.usbserial-* ). " +
                             "For Ganglion, MAC address of the board. For both, AUTO to attempt auto-detection.")
    parser.set_defaults(port="AUTO")
    # baud rate is not currently used
    parser.add_argument('-b', '--baud', default=115200, type=int,
                        help="Baud rate (not currently used)")
    parser.add_argument('--no-filtering', dest='filtering',
                        action='store_false',
                        help="Disable notch filtering")
    parser.set_defaults(filtering=True)
    parser.add_argument('-d', '--daisy', dest='daisy',
                        action='store_true',
                        help="Force daisy mode (cyton board)")
    parser.add_argument('-x', '--aux', dest='aux',
                        action='store_true',
                        help="Enable accelerometer/AUX data (ganglion board)")
    # first argument: plugin name, then parameters for plugin
    parser.add_argument('-a', '--add', metavar=('PLUGIN', 'PARAM'),
                        action='append', nargs='+',
                        help="Select which plugins to activate and set parameters.")
    parser.add_argument('--log', dest='log', action='store_true',
                        help="Log program")
    parser.add_argument('--plugins-path', dest='plugins_path', nargs='+',
                        help="Additional path(s) to look for plugins")

    parser.set_defaults(daisy=False, log=False)

    args = parser.parse_args()

    if not args.add:
        print("WARNING: no plugin selected, you will only be able to communicate with the board. "
              "You should select at least one plugin with '--add [plugin_name]'. "
              "Use '--list' to show available plugins or '--info [plugin_name]' to get more information.")

    import openbci.cyton as bci

    #Load plugins
    plugins_paths = ["openbci/plugins"]
    if args.plugins_path:
        plugins_paths += args.plugins_path
    manager.setPluginPlaces(plugins_paths)
    manager.collectPlugins()

    print("\n------------SETTINGS-------------")
    print("Notch filtering:" + str(args.filtering))

    print("\n-------INSTANTIATING BOARD-------")
    board = bci.OpenBCICyton(port=args.port,
                                 baud=args.baud,
                                 daisy=args.daisy,
                                 filter_data=args.filtering,
                                 scaled_output=True,
                                 log=args.log)
    
    print("\n------------PLUGINS--------------")
    # Loop round the plugins and print their names.
    print("Found plugins:")
    for plugin in manager.getAllPlugins():
        print("[ " + plugin.name + " ]")
    print("\n")

    # Fetch plugins, try to activate them, add to the list if OK
    plug_list = []
    callback_list = []
    if args.add:
        for plug_candidate in args.add:
            # first value: plugin name, then optional arguments
            plug_name = plug_candidate[0]
            plug_args = plug_candidate[1:]
            # Try to find name
            plug = manager.getPluginByName(plug_name)
            if plug == None:
                # eg: if an import fail inside a plugin, yapsy skip it
                print("Error: [ " + plug_name + " ] not found or could not be loaded. Check name and requirements.")
            else:
                print("\nActivating [ " + plug_name + " ] plugin...")
                if not plug.plugin_object.pre_activate(plug_args, sample_rate=board.getSampleRate(),
                                                       eeg_channels=board.getNbEEGChannels(),
                                                       aux_channels=board.getNbAUXChannels(),
                                                       imp_channels=board.getNbImpChannels()):
                    print("Error while activating [ " + plug_name + " ], check output for more info.")
                else:
                    print("Plugin [ " + plug_name + "] added to the list")
                    plug_list.append(plug.plugin_object)
                    callback_list.append(plug.plugin_object)

    if len(plug_list) == 0:
        fun = None
    else:
        fun = callback_list

    def cleanUp():
        board.disconnect()
        print("Deactivating Plugins...")
        for plug in plug_list:
            plug.deactivate()
        print("User.py exiting...")

    atexit.register(cleanUp)

    print("\n-------------BEGIN---------------")
    # Init board state
    # s: stop board streaming; v: soft reset of the 32-bit board (no effect with 8bit board)
    s = 'sv'
    # Tell the board to enable or not daisy module
    if board.daisy:
        s = s + 'C'
    else:
        s = s + 'c'
    # d: Channels settings back to default
    s = s + 'd'

def set_registers(s):
        
    if board.streaming and s != "/stop":
        print("Error: the board is currently streaming data, please type '/stop' before issuing new commands.")
    else:
        # read silently incoming packet if set (used when stream is stopped)
        flush = False
        s = s[1:]

        if "T:" in s:
            lapse = int(s[string.find(s, "T:") + 2:])
        elif "t:" in s:
            lapse = int(s[string.find(s, "t:") + 2:])
        else:
            lapse = -1

        if "start" in s:
            board.setImpedance(False)
            if fun != None:
                # start streaming in a separate thread so we could always send commands in here
                boardThread = threading.Thread(target=board.start_streaming, args=(fun, lapse))
                boardThread.daemon = True  # will stop on exit
                try:
                    boardThread.start()
                except:
                    raise
            else:
                print("No function loaded")

        elif 'stop' in s:
            board.stop()
            flush = True

        line = ''
        time.sleep(0.1)  # Wait to see if the board has anything to report
        # The Cyton nicely return incoming packets -- here supposedly messages
        # whereas the Ganglion prints incoming ASCII message by itself
        while board.ser_inWaiting():
            # we're supposed to get UTF8 text, but the board might behave otherwise
            c = board.ser_read().decode('utf-8', errors='replace')
            line += c
            time.sleep(0.001)
            if (c == '\n') and not flush:
                print('%\t' + line[:-1])
                line = ''
        
        if not flush:
            print(line)

set_registers("/start")