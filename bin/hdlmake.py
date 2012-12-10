#!/usr/bin/env python
#
# Copyright (C) 2009-2012 Chris McClelland
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

# Exception type
class HDLException(Exception):
    pass

# Get the named GitHub repo
def getRepo(meta, proj):
    cwd = os.getcwd()
    if ( not os.path.exists(meta) ):
        mkdir(meta)
    os.chdir(meta)
    
    if ( not os.path.exists(proj) ):
        url = "https://github.com/" + meta + "/" + proj + "/archive/master.tar.gz"
        print "Fetching " + url
        response = urllib2.urlopen(url)
        tar = tarfile.open(mode="r|gz", fileobj=response.fp)
        tar.extractall()
        tar.close()
        os.rename(proj + "-master", proj)
    os.chdir(cwd)

# Make the directory if it doesn't exist
def mkdir(path):
    if ( not os.path.exists(path) ):
        os.makedirs(path)

# Find the name of the top-level module in the given HDL file
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
def isSomethingMissing(directory, fileList):
    for thisFile in fileList:
        if ( thisFile[0] != '+' and thisFile[1] != '/' and not os.path.exists(directory + "/" + thisFile ) ):
            return True
    return False

def varReplace(path, varMap):
    for key in varMap.keys():
        path = path.replace("${" + key + "}", varMap[key])
    return path

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

def getDependencies(varMap, baseDir = None):
    # Construct the real path of the hdlmake.cfg file
    hmFile = "hdlmake.cfg" if baseDir == None else baseDir + "/hdlmake.cfg"

    # Check it exists:
    if ( not os.path.exists(hmFile) ):
        return (None, [], None)

    # Load it:
    tree = yaml.load(file(hmFile, "r"), yaml.BaseLoader)

    # Get the application's own HDLs
    dirHdls = tree["hdls"]

    # Get the deduplicated list of HDL files, recursively including library HDLs
    allHdls = set()
    for hdl in dirHdls:
        addHdl(allHdls, baseDir, hdl, varMap)
    return (dirHdls[0], sorted(allHdls), tree)

def getHdls():
    # Load the hdlmake.cfg file from the current directory
    tree = yaml.load(file('hdlmake.cfg', 'r'), yaml.BaseLoader)

    # Get the application's own HDLs
    appHdls = tree["hdls"]

    # Get the deduplicated list of HDL files, recursively including library HDLs
    allHdls = []
    for hdl in appHdls:
        if ( hdl[0] == '+' and hdl[1] == '/' ):
            appendLib(allHdls, topDir + "/libs", hdl[2:])
        else:
            allHdls.append(hdl)
    return (appHdls[0], sorted(set(allHdls)))

# Build the current directory
def appBuild(template, platform):
    # Load the app hdlmake.cfg & template hdlmake.cfg
    varMap = {"platform": platform}
    (appTop, appHdls, appTree) = getDependencies(varMap)
    (templateTop, templateHdls, templateTree) = getDependencies(varMap, template)

    # Load platform.cfg
    platformDir = os.path.dirname(template) + "/platforms/" + platform
    platformTree = yaml.load(file(platformDir + "/platform.cfg"), yaml.BaseLoader)
    vendor = platformTree["vendor"]
    
    # Get the deduplicated list of app & template HDL files
    appHdls.extend(templateHdls)
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
            shutil.copy(platformDir + "/platform.ucf", subdir)
        return

    # Proceed with the build
    if ( vendor == "xilinx" ):
        # Get Xilinx-specific settings from platform.cfg
        mapFlags = platformTree["map_flags"]
        parFlags = platformTree["par_flags"]
        if ( mapFlags == None ):
            mapFlags = ""
        if ( parFlags == None ):
            parFlags = ""
        fpga = platformTree["fpga"]
        
        # Create list of HDLs
        f = open("top_level.prj", "w")
        for i in uniqueHdls:
            if ( i.endswith(".vhdl") or i.endswith(".vhd") ):
                f.write("vhdl work \"" + i.replace("${platform}", platform) + "\"\n")
            elif ( i.endswith(".v") ):
                f.write("verilog work \"" + i.replace("${platform}", platform) + "\"\n")
        f.close()
        
        # Run the build steps
        mkdir("xst/projnav.tmp")
        if ( os.system("xst -intstyle ise -ifn " + platformDir + "/platform.xst -ofn top_level.syr") ):
            raise HDLException("The xst process failed")
        if ( os.system("ngdbuild -intstyle ise -dd _ngo -nt timestamp -uc " + platformDir + "/platform.ucf -p " + fpga + " top_level.ngc top_level.ngd") ):
            raise HDLException("The ngdbuild process failed")
        if ( os.system("map -intstyle ise -p " + fpga + " " + mapFlags + " -ir off -pr off -c 100 -w -o top_level_map.ncd top_level.ngd top_level.pcf") ):
            raise HDLException("The map process failed")
        if ( os.system("par -w -intstyle ise -ol high " + parFlags + " top_level_map.ncd top_level.ncd top_level.pcf") ):
            raise HDLException("The par process failed")
        if ( os.system("bitgen -intstyle ise -f " + platformDir + "/platform.ut top_level.ncd") ):
            raise HDLException("The bitgen process failed")
        
        # Generate iMPACT batch script from platform's template file
        f = open(platformDir + "/platform.batch", "r")
        batch = f.read()
        f.close()

        # Infer XILINX variable from system PATH
        xilinx = None
        for i in os.environ['PATH'].split(os.pathsep):
            xstName = "xst.exe" if ( os.name == 'nt' ) else "xst"
            if ( os.path.exists(i + os.path.sep + xstName) ):
                xilinx = i[:i.rfind("ISE")] + "ISE"
                break
        if ( xilinx == None ):
            raise HDLException("Cannot infer Xilinx root from system PATH")

        batch = batch.replace("${XILINX}", xilinx)
        f = open("temp.batch", "w")
        f.write("setPreference -pref KeepSVF:True\n")
        f.write(batch)
        f.close()
        if ( os.system("impact -batch temp.batch") ):
            raise HDLException("The impact process failed")
        os.remove("temp.batch")
    elif ( vendor == "altera" ):
        # Copy platform.qsf & platform.sdc over
        shutil.copyfile(platformDir + "/platform.qsf", "top_level.qsf")
        shutil.copyfile(platformDir + "/platform.sdc", "top_level.sdc")
        
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
    varMap = {"platform": "sim"}
    (topHdl, uniqueHdls, tree) = getDependencies(varMap)

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
                    m = re.search(r"^WARNING:Xst:(\d+)\s+-\s+(.*?)$", l)
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
    for i in ["*.bak", "*.bgn", "*.bit", "*.bld", "*.cmd", "*.cmd_log", "*.csv", "*.csvf",
              "*.done", "*.dpf", "*.drc", "*.edif", "*.gise", "*.html", "*.ise", "*.jdi",
              "*.log", "*.lso", "*.map", "*.mrp", "*.ncd", "*.ngc", "*.ngd", "*.ngm", "*.ngr",
              "*.ntrc_log", "*.pad", "*.par", "*.pcf", "*.pin", "*.pof", "*.prj", "*.ptwx",
              "*.qpf", "*.qsf", "*.rpt", "*.sdc", "*.smsg", "*.sof", "*.srf", "*.stx",
              "*.summary", "*.svf", "*.syr", "*.twr", "*.twr", "*.twx", "*.txt", "*.unroutes",
              "*.xml", "*.xpi", "*.xrpt", "*.xsvf", "*.xwbt"]:
        wildcardDelete(i)
    for i in ["results.sim"]:
        if ( os.path.exists(i) ):
            os.remove(i)
    for i in ["xst", "db", "incremental_db", "_ngo", "_xmsgs", "auto_project_xdb", "iseconfig", "xlnx_auto_0_xdb", "simulation", "synthesis"]:
        if ( os.path.exists(i) ):
            shutil.rmtree(i)
    foreachTestbench(doClean)

def topBuild():
    dirname = os.path.basename(os.getcwd())
    if ( dirname[:3] == "tb_" ):
        # We're building in a test directory
        print "[Testbench: " + dirname + "]"
        varMap = {"platform": "sim"}
        (tbTop, tbHdls, tbTree) = getDependencies(varMap)
        tbTopLevel = os.path.splitext(os.path.basename(tbTop))[0]
        cwd = os.getcwd()
        os.chdir("..")
        if ( argList.v ):
            doValidate(argList.v[0])
        (appTop, appHdls, appTree) = getDependencies(varMap)
        tbHdls.extend([i if i.startswith(topDir) else "../" + i for i in appHdls])
        os.chdir(cwd)
        if ( isBuildNeeded("simulation/TIMESTAMP", tbHdls) ):
            print "HDL simulation:"
            if ( os.path.exists("simulation") ):
                shutil.rmtree("simulation")
            mkdir("simulation")
            open("simulation/TIMESTAMP", "a").close()
            os.utime("simulation/TIMESTAMP", (0, 0))  # set last-mod time to 1970
            if ( os.system("ghdl -i --ieee=synopsys --std=93c --vital-checks --warn-binding --warn-reserved --warn-library --warn-vital-generic --warn-delayed-checks --warn-body --warn-specs --warn-unused --warn-error --workdir=simulation --work=work " + " ".join(tbHdls)) ):
                raise HDLException("The ghdl first stage build failed")
            if ( os.system("ghdl -m --ieee=synopsys --std=93c --vital-checks --warn-binding --warn-reserved --warn-library --warn-vital-generic --warn-delayed-checks --warn-body --warn-specs --warn-unused --warn-error --workdir=simulation --work=work " + tbTopLevel) ):
                raise HDLException("The ghdl second stage build failed")
            shutil.move(tbTopLevel, "simulation")
            if ( os.system("./simulation/" + tbTopLevel + " --stop-time=41280ns --wave=simulation/" + tbTopLevel + ".ghw") ):
                raise HDLException("The ghdl simulation failed")
            if ( os.path.exists("expected.sim") and os.path.exists("results.sim") ):
                if ( not filecmp.cmp("expected.sim", "results.sim") ):
                    raise HDLException("The simulation produced unexpected results")
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
                    f.write("gtkwave::addSignalsFromList " + i + "\n")
            f.write("gtkwave::setZoomFactor -26\n")
            f.write("gtkwave::setMarker 600ns\n")
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
        platform = argList.p[0] if argList.p else None

        # Load the hdlmake.cfg file from the current directory
        if ( template == None ):
            if ( platform != None ):
                raise HDLException("I have a platform but no template")
            # else
            #   do nothing
        else:
            if ( platform == None ):
                raise HDLException("I have a template but no platform")
            else:
                appBuild(template, platform)

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

def doZero():
    batchList = glob.glob("*.batch")
    if ( len(batchList) != 1 ):
        raise HDLException("Refusing to zero a directory which does not contain exactly one .batch file")
    allList = sorted(glob.glob("*"))
    print "Current directory contains:"
    for i in allList:
        if ( i.endswith(".batch") or i == "hdlmake.cfg" ):
            print "  " + i + " *"
        else:
            print "  " + i
    yn = raw_input('\nThis operation will erase everything apart from *.batch and\nhdlmake.cfg. Are you sure you want to proceed? ')
    if ( yn.upper() == 'Y' ):
        files = glob.glob("*")
        for i in files:
            if ( not i.endswith(".batch") and i != "hdlmake.cfg" ):
                if ( os.path.isdir(i) ):
                    shutil.rmtree(i)
                else:
                    os.remove(i)
    else:
        raise HDLException("Batch zero operation aborted")

# Main function if we're not loaded as a module
if __name__ == "__main__":
    print "MakeStuff HDL Builder (C) 2012 Chris McClelland\n"
    parser = argparse.ArgumentParser(description='Build and test HDL code.')
    parser.add_argument('-c', action="store_true", default=False, help="clean the current directory and exit")
    parser.add_argument('-t', action="store", nargs=1, metavar="<template>", help="the template to build with")
    parser.add_argument('-p', action="store", nargs=1, metavar="<platform>", help="the platform to build for")
    parser.add_argument('-a', action="store", nargs=1, metavar="<subdir>", help="make the named subdir and launch qmegawiz")
    parser.add_argument('-x', action="store", nargs=1, metavar="<subdir>", help="make the named subdir and launch coregen")
    parser.add_argument('-z', action="store_true", default=False, help="clean the current coregen/megawiz directory and exit")
    parser.add_argument('-v', action="store", nargs=1, metavar="<x|a>", help="validate with either Xilinx or Altera")
    parser.add_argument('-w', action="store_true", default=False, help="display the simulation waves")
    parser.add_argument('-i', action="store", nargs=1, metavar="<subdir>", help="copy files locally in preparation for an IDE build")
    parser.add_argument('-g', action="store", nargs=1, metavar="<meta/proj>", help="fetch the specified GitHub repo")
    argList = parser.parse_args()
    try:
        if ( argList.c ):
            doClean()
        elif ( argList.z ):
            doZero()
        elif ( argList.g ):
            (meta, proj) = argList.g[0].split("/")
            getRepo(meta, proj)
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
