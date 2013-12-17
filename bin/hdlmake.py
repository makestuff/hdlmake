#!/usr/bin/env python
#
# Copyright (C) 2012-2013 Chris McClelland
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
import yaml
import sys, os, errno
import argparse
import shutil
import glob
import re
import filecmp
import urllib2
import tarfile

topDir = os.path.dirname(os.path.dirname(os.path.realpath(sys.argv[0]))).replace("\\", "/")
argList = 0
warnSet = set(["647"])     # The set of xst warnings which should be treated as warnings
ignoreSet = set(["2036"])  # The set of xst warnings which should be ignored altogether
branch = "master"

# Exception type
#
class HDLException(Exception):
    pass

# Fetch the named GitHub repo using HTTP
#
def getRepo(user, repo):
    cwd = os.getcwd()
    if ( not os.path.exists(user) ):
        mkdir(user)
    os.chdir(user)
    
    if ( not os.path.exists(repo) ):
        url = "https://github.com/" + user + "/" + repo + "/archive/" + branch + ".tar.gz"
        print "Fetching " + url
        response = urllib2.urlopen(url)
        tar = tarfile.open(mode="r|gz", fileobj=response.fp)
        tar.extractall()
        tar.close()
        os.rename(repo + "-" + branch, repo)
    os.chdir(cwd)

# Make the directory if it doesn't exist
#
def mkdir(path):
    if ( not os.path.exists(path) ):
        os.makedirs(path)

# Find the name of the top-level module in the given HDL file
#
def findTop(hdl):
    file = ""
    baseName = os.path.basename(hdl).lower()
    if ( baseName.endswith(".v") ):
        for line in open(hdl):
            file = file + re.sub(r'^(.*?)(//.*?)?\n', r'\1', line)
        return re.sub(r'^.*?[mM][oO][dD][uU][lL][eE]\s+(\w+)\s*#?\s*\(.*?$', r'\1', file.replace('\t', ' '))
    elif ( baseName.endswith(".vhdl") or baseName.endswith(".vhd") ):
        for line in open(hdl):
            file = file + re.sub(r'^(.*?)(--.*?)?\n', r'\1', line)
        noTabs = file.replace('\t', ' ')
        topName = re.sub(r'^.*?[aA][rR][cC][hH][iI][tT][eE][cC][tT][uU][rR][eE]\s+\w+\s+[oO][fF]\s+(\w+)\s*[iI][sS].*?$', r'\1', noTabs)
        if ( topName == noTabs ):
            topName = re.sub(r'^.*?[eE][nN][tT][iI][tT][yY]\s+(\w+)\s*[iI][sS].*?$', r'\1', noTabs)
        return topName

# Find out if one or more of the specified files is missing from the specified directory
#
def isSomethingMissing(directory, fileList):
    for thisFile in fileList:
        if ( thisFile[0] != '+' and thisFile[1] != '/' and not os.path.exists(directory + "/" + thisFile ) ):
            return True
    return False

# Replace any variables in "path" with their value from "varMap"
#
def varReplace(path, varMap):
    for key in varMap.keys():
        path = path.replace("${" + key + "}", varMap[key])
    return path

# Called by addHdl()
#
def addLibrary(hdlSet, baseDir, varMap):
    tree = yaml.load(file(baseDir + "/hdlmake.cfg"), yaml.BaseLoader)
    hdls = tree["hdls"]
    ngcs = [] if "ngcs" not in tree else tree["ngcs"]
    if ( isSomethingMissing(baseDir, hdls) or isSomethingMissing(baseDir, ngcs) ):
        print "Something missing - running the generation rule"
        if ( "gen" in tree ):
            cwd = os.getcwd()
            os.chdir(baseDir)
            if ( os.system(tree["gen"]) ):
                raise HDLException("The generation rule for " + baseDir + " failed")
            os.chdir(cwd)
        else:
            raise HDLException("A required file is missing from " + baseDir + " and no generation rule was specified")
    for hdl in hdls:
        addHdl(hdlSet, baseDir, hdl, varMap)
    for ngc in ngcs:
        shutil.copyfile(baseDir + "/" + ngc, ngc)

# Called by getDependencies() and addLibrary()
#
def addHdl(hdlSet, baseDir, hdl, varMap):
    if ( hdl[0] == '+' and hdl[1] == '/' ):
        # This is a top-level library import
        baseDir = topDir + "/libs/" + hdl[2:]
        baseDir = varReplace(baseDir, varMap)
        if ( not os.path.exists(baseDir) ):
            cwd = os.getcwd()
            os.chdir(topDir + "/libs")
            dirs = hdl[2:].split("/")
            getRepo(dirs[0], dirs[1])
            os.chdir(cwd)
        addLibrary(hdlSet, baseDir, varMap)
    else:
        # It's a relative path; make it absolute
        if ( baseDir != None ):
            hdl = baseDir + "/" + hdl
        hdl = varReplace(hdl, varMap)
        if ( os.path.isdir(hdl) ):
            # This is a library import
            addLibrary(hdlSet, hdl, varMap)
        else:
            # This is just an HDL file
            hdlSet.add(hdl)

# Read the hdlmake.cfg from the specified directory
#
def readHdlMake(baseDir, isRequired = True):
    # Construct the real path of the hdlmake.cfg file
    hmFile = "hdlmake.cfg" if baseDir == None else baseDir + "/hdlmake.cfg"
    if ( os.path.exists(hmFile) ):
        return yaml.load(file(hmFile, "r"), yaml.BaseLoader)
    elif ( isRequired ):
        raise HDLException(hmFile + " not found")
    else:
        return None

# Called by appBuild(), doValidate() and topBuild()
#
def getDependencies(tree, baseDir, varMap):
    # Get the application's own HDLs
    dirHdls = tree["hdls"]

    # Get the deduplicated list of HDL files, recursively including library HDLs
    allHdls = set()
    for hdl in dirHdls:
        addHdl(allHdls, baseDir, hdl, varMap)
    return (dirHdls[0], sorted(allHdls))

# Build the current directory - called by topBuild()
#
def appBuild(template, board):
    # Load the app hdlmake.cfg & template hdlmake.cfg
    varMap = {"board": board}
    appTree = readHdlMake(None)
    (appTop, appHdls) = getDependencies(appTree, None, varMap)
    templateTree = readHdlMake(template, False)
    if ( templateTree ):
        (templateTop, templateHdls) = getDependencies(templateTree, template, varMap)
        appHdls.extend(templateHdls)
    
    # Load board.cfg
    boardDir = template + "/boards/" + board
    if ( not os.path.exists(boardDir) ):
        boardDir = os.path.dirname(template) + "/boards/" + board
    boardTree = yaml.load(file(boardDir + "/board.cfg"), yaml.BaseLoader)
    vendor = boardTree["vendor"]
    
    # Get the deduplicated list of app & template HDL files
    uniqueHdls = sorted(set(appHdls))

    print "Unique HDLs:"
    for i in uniqueHdls:
        print "  " + i

    # If all we need is a local copy for doing an IDE build, we can exit early
    if ( argList.i ):
        subdir = argList.i[0]
        mkdir(subdir)
        for i in uniqueHdls:
            shutil.copy(i, subdir)
        if ( vendor == "xilinx" ):  # TODO: what about Altera?
            ngcList = glob.glob("*.ngc")
            for i in ngcList:
                shutil.copy(i, subdir)
            shutil.copy(boardDir + "/board.ucf", subdir)
        return

    # Proceed with the build
    if ( vendor == "xilinx" ):
        # Create list of HDLs
        f = open("top_level.prj", "w")
        for i in uniqueHdls:
            if ( i.endswith(".vhdl") or i.endswith(".vhd") ):
                f.write("vhdl work \"" + i.replace("${board}", board) + "\"\n")
            elif ( i.endswith(".v") ):
                f.write("verilog work \"" + i.replace("${board}", board) + "\"\n")
        f.close()

        # Synthesis
        mkdir("xst/projnav.tmp")
        if ( os.system("xst -intstyle ise -ifn " + boardDir + "/board.xst -ofn top_level.syr") ):
            raise HDLException("The xst process failed")

        # Get Xilinx-specific settings from board.cfg
        if ( "fpga" in boardTree ):
            fpga = boardTree["fpga"]
            mapFlags = boardTree["map_flags"]
            parFlags = boardTree["par_flags"]
            if ( mapFlags == None ):
                mapFlags = ""
            if ( parFlags == None ):
                parFlags = ""

            # Run the FPGA build steps
            if ( os.system("ngdbuild -intstyle ise -dd _ngo -nt timestamp -uc " + boardDir + "/board.ucf -p " + fpga + " top_level.ngc top_level.ngd") ):
                raise HDLException("The ngdbuild process failed")
            if ( os.system("map -intstyle ise -p " + fpga + " " + mapFlags + " -ir off -pr off -c 100 -w -o top_level_map.ncd top_level.ngd top_level.pcf") ):
                raise HDLException("The map process failed")
            if ( os.system("par -w -intstyle ise -ol high " + parFlags + " top_level_map.ncd top_level.ncd top_level.pcf") ):
                raise HDLException("The par process failed")
            if ( os.system("bitgen -intstyle ise -f " + boardDir + "/board.ut top_level.ncd") ):
                raise HDLException("The bitgen process failed")
        elif ( "cpld_ngd" in boardTree and "cpld_fit" in boardTree ):
            cpld_ngd = boardTree["cpld_ngd"]
            cpld_fit = boardTree["cpld_fit"]

            # Run the CPLD build steps
            if ( os.system("ngdbuild -intstyle ise -dd _ngo -uc " + boardDir + "/board.ucf -p " + cpld_ngd + " top_level.ngc top_level.ngd") ):
                raise HDLException("The ngdbuild process failed")
            if ( os.system("cpldfit -intstyle ise -p " + cpld_fit + " -ofmt vhdl -optimize speed -htmlrpt -loc on -slew fast -init low -inputs 54 -pterms 25 -unused float -power std -terminate keeper top_level.ngd") ):
                raise HDLException("The cpldfit process failed")
            if ( os.system("hprep6 -s IEEE1149 -n top_level -i top_level") ):
                raise HDLException("The hprep6 process failed")
        else:
            raise HDLException("The " + boardDir + "/board.cfg describes something which is not recognisable as a Xilinx FPGA or CPLD")

        if ( argList.p ):
            # Infer XILINX variable from system PATH
            xilinx = None
            for i in os.environ['PATH'].split(os.pathsep):
                xstName = "xst.exe" if ( os.name == 'nt' ) else "xst"
                if ( os.path.exists(i + os.path.sep + xstName) ):
                    xilinx = i[:i.rfind("ISE")] + "ISE"
                    break
            if ( xilinx == None ):
                raise HDLException("Cannot infer Xilinx root from system PATH")
        
            genRules = boardTree["genrules"] if ( "genrules" in boardTree ) else dict()
            for batch in argList.p:
                # Get list of prerequisite commands
                cmdList = genRules[batch] if ( batch in genRules ) else []
        
                # Generate iMPACT batch script from board's template file
                f = open(boardDir + "/" + batch + ".batch", "r")
                batch = f.read()
                f.close()
        
                batch = batch.replace("${XILINX}", xilinx)
                f = open("temp.batch", "w")
                f.write("setPreference -pref KeepSVF:True\n")
                f.write(batch)
                f.close()
                for i in cmdList:
                    if ( os.system(i) ):
                        raise HDLException("The impact process failed")
                if ( os.system("impact -batch temp.batch") ):
                    raise HDLException("The impact process failed")
                os.remove("temp.batch")
    elif ( vendor == "altera" ):
        # Copy board.qsf & board.sdc over
        shutil.copyfile(boardDir + "/board.qsf", "top_level.qsf")
        shutil.copyfile(boardDir + "/board.sdc", "top_level.sdc")
        
        # Append list of HDLs
        f = open("top_level.qsf", "a")
        for i in uniqueHdls:
            if ( i.endswith(".vhdl") or i.endswith(".vhd") ):
                f.write("set_global_assignment -name VHDL_FILE " + i + "\n")
            elif ( i.endswith(".v") ):
                f.write("set_global_assignment -name VERILOG_FILE " + i + "\n")
        f.close()
        
        # Create top_level.srf file declaring which warnings to ignore
        f = open("top_level.srf", "w")
        f.write('{ "Warning" "WCPT_FEATURE_DISABLED_POST" "LogicLock " "Warning (292013): Feature LogicLock is only available with a valid subscription license. You can purchase a software subscription to gain full access to this feature." {  } {  } 0 292013 "Feature %1!s! is only available with a valid subscription license. You can purchase a software subscription to gain full access to this feature." 1 0 "" 0 -1}\n')
        f.close()
    
        # Run the build steps
        if ( os.system("quartus_map --parallel=1 --read_settings_files=on --write_settings_files=off top_level -c top_level") ):
            raise HDLException("The quartus_map process failed")
        if ( os.system("quartus_fit --parallel=1 --read_settings_files=on --write_settings_files=off top_level -c top_level") ):
            raise HDLException("The quartus_fit process failed")
        if ( os.system("quartus_asm --read_settings_files=on --write_settings_files=off top_level -c top_level") ):
            raise HDLException("The quartus_asm process failed")

# Work out whether a build is needed by comparing datestamps
def isBuildNeeded(target, hdls):
    if ( os.path.exists(target) ):
        synModTime = os.path.getmtime(target)
        for i in hdls:
            if ( os.path.getmtime(i) > synModTime ):
                return True  # something modified; rebuild
        return False  # nothing more recent than target, no need to build
    else:
        return True  # no target yet, must build

# Validate the syntax of the code in the current directory by running only the synthesis step
def doValidate(tool):
    # Load the hdlmake.cfg file from the current directory
    varMap = {"board": "sim"}
    tree = readHdlMake(None)
    (topHdl, uniqueHdls) = getDependencies(tree, None, varMap)

    print "Unique HDLs:"
    for i in uniqueHdls:
        print "  " + i

    if ( isBuildNeeded("synthesis/TIMESTAMP", uniqueHdls) ):
        # Separate directory for synthesis gubbins
        print "HDL validation:"
        mkdir("synthesis")
        os.chdir("synthesis")
        open("TIMESTAMP", "a").close()
        os.utime("TIMESTAMP", (0, 0))  # set last-mod time to 1970

        topLevel = findTop("../" + topHdl)
        print "Deduced top-level entity: " + topLevel

        if ( tool == 'x' ):
            # Create list of HDLs
            f = open("top_level.prj", "w")
            for i in uniqueHdls:
                fn = i if i.startswith(topDir) else "../" + i
                if ( i.endswith(".vhdl") or i.endswith(".vhd") ):
                    f.write("vhdl work \"" + fn + "\"\n")
                elif ( i.endswith(".v") ):
                    f.write("verilog work \"" + fn + "\"\n")
            f.close()

            # Generate xst file.
            f = open("top_level.xst", "w")
            f.write("set -tmpdir \"xst/projnav.tmp\"\n")
            f.write("set -xsthdpdir \"xst\"\n")
            f.write("run\n")
            f.write("-ifn top_level.prj\n")
            f.write("-ifmt mixed\n")
            f.write("-ofn " + topLevel + "\n")
            f.write("-ofmt NGC\n")
            f.write("-p xc6slx9-2-tqg144\n")
            f.write("-top " + topLevel + "\n")
            f.write("-opt_mode Speed\n")
            f.write("-opt_level 1\n")
            f.close()
        
            # Run the build steps
            mkdir("xst/projnav.tmp")
            if ( os.system("xst -intstyle ise -ifn top_level.xst -ofn top_level.syr") ):
                raise HDLException("The xst process failed")

            # Extract warning info
            f = open(topLevel + "_xst.xrpt", "r")
            m = None
            while ( m == None ):
                l = f.readline()
                if ( l == "" ):
                    raise HDLException("Report file is missing warning information")
                m = re.search(r"XST_NUMBER_OF_WARNINGS\" value=\"(\d+)\"", l)
            f.close()
            if ( m.group(1) != "0" ):
                warnCount = 0
                errCount = 0
                ignoreCount = 0
                warnMsgs = ""
                errMsgs = ""
                f = open("top_level.syr", "r")
                m = None
                l = f.readline()
                while ( l != "" ):
                    m = re.search(r"^WARNING:[A-Za-z]+:(\d+)\s+-\s+(.*?)$", l)
                    if ( m != None ):
                        code = m.group(1)
                        msg = m.group(2)
                        if ( code in warnSet ):
                            warnCount += 1
                            warnMsgs += "\n  " + code + ": " + msg
                        elif ( code not in ignoreSet ):
                            errCount += 1
                            errMsgs += "\n  " + code + ": " + msg
                        else:
                            ignoreCount += 1
                    l = f.readline()
                f.close()
                if ( warnCount ):
                    if ( ignoreCount ):
                        print "\nFound {0} warnings (ignored {1}):{2}\n".format(warnCount, ignoreCount, warnMsgs)
                    else:
                        print "\nFound {0} warnings:{1}\n".format(warnCount, warnMsgs)
                if ( errCount ):
                    raise HDLException("Found {0} errors:{1}".format(errCount, errMsgs))
        elif ( tool == 'a' ):
            # Generate qsf file
            f = open("top_level.qsf", "w")
            f.write("set_global_assignment -name FAMILY \"Cyclone II\"\n")
            f.write("set_global_assignment -name DEVICE EP2C5T144C8\n")
            f.write("set_global_assignment -name TOP_LEVEL_ENTITY " + topLevel + "\n")

            for i in uniqueHdls:
                fn = (i if i.startswith(topDir) else "../" + i)
                if ( i.endswith(".vhdl") or i.endswith(".vhd") ):
                    f.write("set_global_assignment -name VHDL_FILE " + fn + "\n")
                elif ( i.endswith(".v") ):
                    f.write("set_global_assignment -name VERILOG_FILE " + fn + "\n")
            f.close()

            # Run the build:
            if ( os.system("quartus_map --parallel=1 --read_settings_files=on --write_settings_files=off top_level -c top_level") ):
                raise HDLException("The quartus_map process failed")

            # Extract warning info
            f = open("top_level.map.rpt", "r")
            m = None
            while ( m == None ):
                l = f.readline()
                if ( l == "" ):
                    raise HDLException("Report file is missing warning information")
                m = re.search(r"^Info: Quartus II Analysis & Synthesis was successful. (\d+) errors, (\d+) warnings", l)
            f.close()
            errCount = m.group(1)
            warnCount = m.group(2)
            if ( warnCount != "0" or errCount != "0" ):
                raise HDLException("Found {0} errors and {1} warnings".format(errCount, warnCount))
        else:
            raise HDLException("Unsupported validation tool: " + tool)
        
        os.utime("TIMESTAMP", None)  # set last-mod time to now
        os.chdir("..")
    else:
        print "HDL validation: Nothing to do"

# Delete wildcards
def wildcardDelete(wildcard):
    files = glob.glob(wildcard)
    for i in files:
        if ( os.path.isdir(i) ):
            shutil.rmtree(i)
        else:
            os.remove(i)

# Do whatever in each testbench directory
def foreachTestbench(func):
    testBenches = glob.glob("tb_*")
    for tb in testBenches:
        os.chdir(tb)
        func()
        os.chdir("..")

# Clean the directory
def doClean():
    for i in ["*.bak", "*.bgn", "*.bin", "*.bit", "*.bld", "*.cfi", "*.cmd", "*.cmd_log", "*.csv", "*.csvf",
              "*.done", "*.dpf", "*.drc", "*.edif", "*.err", "*.gise", "*.gyd", "*.html", "*.ise", "*.jdi", "*.jed",
              "*.log", "*.lso", "*.map", "*.mcs", "*.mfd", "*.mrp", "*.ncd", "*.ngc", "*.ngd", "*.ngm", "*.ngr",
              "*.ntrc_log", "*.pad", "*.par", "*.pcf", "*.pin", "*.pnx", "*.pof", "*.prj", "*.prm", "*.ptwx",
              "*.qpf", "*.qsf", "*.rpt", "*.sdc", "*.smsg", "*.sof", "*.srf", "*.stx",
              "*.summary", "*.svf", "*.syr", "*.tspec", "*.twr", "*.twr", "*.twx", "*.txt", "*.unroutes",
              "*.vm6", "*.xml", "*.xpi", "*.xrpt", "*.xsvf", "*.xwbt"]:
        wildcardDelete(i)
    for i in ["results.sim"]:
        if ( os.path.exists(i) ):
            os.remove(i)
    for i in ["xst", "db", "incremental_db", "_ngo", "_xmsgs", "auto_project_xdb", "iseconfig", "xlnx_auto_0_xdb", "top_level_html", "simulation", "synthesis", "results"]:
        if ( os.path.exists(i) ):
            shutil.rmtree(i)
    foreachTestbench(doClean)

def topBuild():
    dirname = os.path.basename(os.getcwd())
    if ( dirname[:3] == "tb_" ):
        # We're building in a test directory
        print "[Testbench: " + dirname + "]"
        varMap = {"board": "sim"}
        tbTree = readHdlMake(None)
        (tbTop, tbHdls) = getDependencies(tbTree, None, varMap)
        tbTopLevel = os.path.splitext(os.path.basename(tbTop))[0]
        cwd = os.getcwd()
        os.chdir("..")
        if ( argList.v ):
            doValidate(argList.v[0])
        appTree = readHdlMake(None)
        (appTop, appHdls) = getDependencies(appTree, None, varMap)
        tbHdls.extend([i if i.startswith(topDir) else "../" + i for i in appHdls])
        os.chdir(cwd)
        if ( isBuildNeeded("simulation/TIMESTAMP", tbHdls) ):
            print "HDL simulation:"
            if ( os.path.exists("simulation") ):
                shutil.rmtree("simulation")
            mkdir("simulation")
            open("simulation/TIMESTAMP", "a").close()
            os.utime("simulation/TIMESTAMP", (0, 0))  # set last-mod time to 1970
            if ( os.path.exists("stimulus") ):
                mkdir("results")
            cmd = "ghdl -i --ieee=synopsys --std=93c --vital-checks --warn-binding --warn-reserved --warn-library --warn-vital-generic --warn-delayed-checks --warn-body --warn-specs --warn-unused --warn-error --workdir=simulation --work=work " + " ".join(tbHdls)
            #print cmd
            if ( os.system(cmd) ):
                raise HDLException("The ghdl first stage build failed")
            cmd = "ghdl -m --ieee=synopsys --std=93c --vital-checks --warn-binding --warn-reserved --warn-library --warn-vital-generic --warn-delayed-checks --warn-body --warn-specs --warn-unused --warn-error --workdir=simulation --work=work " + tbTopLevel
            #print cmd
            if ( os.system(cmd) ):
                raise HDLException("The ghdl second stage build failed")
            print "Moving " + tbTopLevel + " to simulation directory"
            shutil.move(tbTopLevel, "simulation")
            stopTime = "41280ns"
            if ( "stopTime" in tbTree ):
                stopTime = tbTree["stopTime"]
            cmd = "./simulation/" + tbTopLevel + " --stop-time=" + stopTime + " --wave=simulation/" + tbTopLevel + ".ghw"
            #print cmd
            if ( os.system(cmd) ):
                raise HDLException("The ghdl simulation failed")
            if ( os.path.exists("expected.sim") ):
                if ( os.path.exists("results.sim") ):
                    if ( not filecmp.cmp("expected.sim", "results.sim") ):
                        raise HDLException("The simulation produced unexpected results")
                else:
                    raise HDLException("The simulation did not produce results")
            if ( os.path.exists("expected") ):
                files = glob.glob("expected/*.sim")
                for expectedFile in files:
                    resultFile = expectedFile.replace("expected", "results")
                    if ( os.path.exists(resultFile) ):
                        if ( not filecmp.cmp(expectedFile, resultFile) ):
                            raise HDLException("The simulation produced unexpected results: %s and %s differ" % (expectedFile, resultFile))
                    else:
                        raise HDLException("The simulation did not produce results: %s missing" % resultFile)
            os.utime("simulation/TIMESTAMP", None)  # set last-mod time to now
        else:
            print "HDL simulation: Nothing to do"

        if ( argList.w and "signals" in tbTree ):
            print "[Preparing GTKWave]"
            signals = tbTree["signals"]
            f = open("simulation/startup.tcl", "w")
            for i in signals:
                if ( i == "---" ):
                    f.write("gtkwave::/Edit/Insert_Blank\n")
                else:
                    f.write(
                        "gtkwave::addSignalsFromList " +
                        i.replace("[", "\\[").replace("]", "\\]") +
                        "\n")
            zoomFactor = "26"
            if ( "zoomFactor" in tbTree ):
                zoomFactor = tbTree["zoomFactor"]
            marker = "600ns";
            if ( "marker" in tbTree ):
                marker = tbTree["marker"]
            windowStartTime = "0ns"
            if ( "windowStartTime" in tbTree ):
                windowStartTime = tbTree["windowStartTime"]
            f.write("gtkwave::setZoomFactor -" + zoomFactor + "\n")
            f.write("gtkwave::setMarker " + marker + "\n")
            f.write("gtkwave::setWindowStartTime " + windowStartTime + "\n")
            f.write("for { set i 0 } { $i <= [ gtkwave::getVisibleNumTraces ] } { incr i } { gtkwave::setTraceHighlightFromIndex $i off }\n")
            f.write("gtkwave::setLeftJustifySigs on\n")
            if ( "sigmaps" in tbTree ):
                for (sigTag, sigMap) in tbTree["sigmaps"].items():
                    sigName = "top." + tbTopLevel + "." + str(sigMap["name"]).replace('[', '\[').replace(']', '\]')
                    sigName = sigName.lower()
                    f.write("gtkwave::highlightSignalsFromList " + sigName + "\n")
                    f.write("set translateFile [ gtkwave::setCurrentTranslateFile simulation/" + sigTag  + ".txt ]\n")
                    f.write("gtkwave::installFileFilter $translateFile\n")
                    f.write("gtkwave::unhighlightSignalsFromList " + sigName + "\n")
                    
                    g = open("simulation/" + sigTag + ".txt", "w")
                    for tag in sigMap:
                        if ( tag != "name" ):
                            g.write("{0} {1}\n".format(tag, sigMap[tag]))
                    g.close()
            f.close()
            os.system("gtkwave -T simulation/startup.tcl simulation/" + tbTopLevel + ".ghw")
    else:
        # Run tests...
        if ( argList.v ):
            print "[Validating HDLs]"
            doValidate(argList.v[0])
        print "[Running tests]"
        foreachTestbench(topBuild)
        print "[Finished testing]"
        template = argList.t[0] if argList.t else None
        board = argList.b[0] if argList.b else None

        # Load the hdlmake.cfg file from the current directory
        if ( template == None ):
            if ( board != None ):
                raise HDLException("I have a board but no template")
            # else
            #   do nothing
        else:
            if ( board == None ):
                raise HDLException("I have a template but no board")
            else:
                appBuild(template, board)

def xilinxBlock(subdir):
    if ( os.path.exists(subdir) ):
        raise HDLException("Xilinx block directory already exists")
    mkdir(subdir)
    os.chdir(subdir)
    #shutil.copyfile("../fifo.xco", "fifo.xco")
    os.system("coregen")
    xcoList = glob.glob("*.xco")
    if ( len(xcoList) != 1 ):
        raise HDLException("COREgen failed to produce exactly one .xco file")
    xcoName = xcoList[0]
    baseName = os.path.splitext(xcoName)[0]
    batchName = baseName + ".batch"
    print "BaseName: " + baseName

    f = open("../" + batchName, "w")
    found = False
    for line in open(xcoList[0]):
        if ( not found and "SET" in line.upper() ):
            found = True
            f.write("NEWPROJECT .\n")
        f.write(line)
    f.close()
    hdlList = glob.glob("*.vhd") + glob.glob("*.v")
    ngcList = glob.glob("*.ngc")
    wildcardDelete("*")
    shutil.move("../" + batchName, batchName)

    f = open("hdlmake.cfg", "w")
    f.write("hdls:\n")
    for i in hdlList:
        f.write("  - " + i + "\n")
    f.write("\nngcs:\n")
    for i in ngcList:
        f.write("  - " + i + "\n")
    f.write("\ngen: coregen -b " + batchName + "\n")
    f.close()

def alteraBlock(subdir):
    if ( os.path.exists(subdir) ):
        raise HDLException("Altera block directory already exists")
    mkdir(subdir)
    os.chdir(subdir)
    os.system("qmegawiz")
    qipList = glob.glob("*.qip")
    if ( len(qipList) != 1 ):
        raise HDLException("MegaWizard failed to produce exactly one .qip file")
    qipName = qipList[0]
    baseName = os.path.splitext(qipName)[0]
    batchName = baseName + ".batch"
    print "BaseName: " + baseName
    
    lpmType = None
    for line in open("greybox_tmp/cbx_args.txt"):
        if ( line.startswith("LPM_TYPE=") ):
            lpmType = line[9:].rstrip()
            break
    if ( lpmType == None ):
        raise HDLException("cbx_args.txt did not specify LPM_TYPE")

    shutil.copyfile("greybox_tmp/cbx_args.txt", "../" + batchName)
    if ( os.path.exists(baseName + ".vhd") ):
        hdlName = baseName + ".vhd"
    elif ( os.path.exists(baseName + ".v") ):
        hdlName = baseName + ".v"
    wildcardDelete("*")
    shutil.move("../" + batchName, batchName)

    f = open("hdlmake.cfg", "w")
    f.write("hdls:\n")
    f.write("  - " + hdlName + "\n\n")
    f.write("gen: qmegawiz -silent module=" + lpmType + " -f:" + batchName + " " + hdlName + "\n")
    f.close()

def doZero(subdir):
    if ( not(os.path.isdir(subdir)) ):
        return
    cwd = os.getcwd()
    os.chdir(subdir)
    batchList = glob.glob("*.batch")
    print "Zeroing " + subdir + ":"
    if ( len(batchList) == 1 ):
        allList = sorted(glob.glob("*"))
        workNeeded = False
        for i in allList:
            if ( i.endswith(".batch") or i == "hdlmake.cfg" ):
                print "  " + i + " *"
            else:
                workNeeded = True;
                print "  " + i
        if ( workNeeded ):
            yn = "Y" if argList.f else raw_input('\nThis operation will erase everything apart from *.batch and\nhdlmake.cfg. Are you sure you want to proceed? ')
            if ( yn.upper() == 'Y' ):
                files = glob.glob("*")
                for i in files:
                    if ( not i.endswith(".batch") and i != "hdlmake.cfg" ):
                        if ( os.path.isdir(i) ):
                            shutil.rmtree(i)
                        else:
                            os.remove(i)
        else:
            print "  Nothing to do here!"
    else:
        print "  Refusing to zero " + subdir + " because it doesn't contain exactly one .batch file"
    os.chdir(cwd)
    
# Main function if we're not loaded as a module
if __name__ == "__main__":
    print "MakeStuff HDL Builder (C) 2012-2013 Chris McClelland\n"
    parser = argparse.ArgumentParser(description='Build and test HDL code.')
    parser.add_argument('-c', action="store_true", default=False, help="clean the current directory and exit")
    parser.add_argument('-t', action="store", nargs=1, metavar="<template>", help="the template to build with")
    parser.add_argument('-b', action="store", nargs=1, metavar="<board>", help="the board to build for")
    parser.add_argument('-a', action="store", nargs=1, metavar="<subdir>", help="make the named subdir and launch qmegawiz")
    parser.add_argument('-x', action="store", nargs=1, metavar="<subdir>", help="make the named subdir and launch coregen")
    parser.add_argument('-z', action="store", nargs="*", metavar="<subdir>", help="clean the specified coregen/megawiz directories and exit")
    parser.add_argument('-v', action="store", nargs=1, metavar="<x|a>", help="validate with either Xilinx or Altera")
    parser.add_argument('-w', action="store_true", default=False, help="display the simulation waves")
    parser.add_argument('-i', action="store", nargs=1, metavar="<subdir>", help="copy files locally in preparation for an IDE build")
    parser.add_argument('-g', action="store", nargs=1, metavar="<user/repo>", help="fetch the specified GitHub repo")
    parser.add_argument('-p', action="store", nargs="*", metavar="<rule>", help="generate the specified programming file(s)")
    parser.add_argument('-f', action="store_true", default=False, help="avoid confirmation when zeroing: DANGEROUS")
    argList = parser.parse_args()

    brFileName = topDir + "/.branch";
    if (os.path.exists(brFileName) ):
        brFile = open(brFileName)
        branch = brFile.read().strip()
        brFile.close()
    try:
        if ( argList.c ):
            doClean()
        elif ( argList.z ):
            for d in argList.z:
                doZero(d)
        elif ( argList.g ):
            (user, repo) = argList.g[0].split("/")
            getRepo(user, repo)
        elif ( argList.x ):
            xilinxBlock(argList.x[0])
        elif ( argList.a ):
            alteraBlock(argList.a[0])
        else:
            topBuild()
        print "Success!"
    except HDLException, ex:
        print "ERROR: " + str(ex)
        exit(3)
