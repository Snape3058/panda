#!/usr/bin/env python3

import os
import sys
import json
import argparse
from subprocess import Popen as popen
from subprocess import PIPE as pipe
import re
import shlex
from ctypes import CDLL as openso
import time
from collections import namedtuple
import textwrap
from multiprocessing import Pool as pool

ExecCommands = namedtuple('ExecCommands',
                          ['method', 'ppid', 'pid', 'pwd', 'arguments'])
CompilingCommands = namedtuple('CompilingCommands',
                               ['compiler', 'directory', 'files', 'arguments',
                                'output', 'oindex', 'compilation'])
LinkingCommands = namedtuple('LinkingCommands',
                             ['linker', 'directory', 'files', 'arguments',
                              'output', 'oindex', 'archive'])
LinkingAlias = namedtuple('LinkingAlias', ['output', 'objects', 'libraries'])
ExecutedCommand = namedtuple('ExecutedCommand',
                             ['output', 'arguments', 'directory'])


# default configurations and strings
class Default:  # {{{
    # configurable names, tags, and other strings
    panda = os.path.abspath(os.path.realpath(__file__))
    pandadir = os.path.dirname(panda)
    execdir = os.getcwd()
    libname = 'libpanda.so'
    libpath = os.path.join(pandadir, libname)
    ast_desc = 'Clang PCH file'
    i_desc = 'C/C++ preprocessed file'
    ll_desc = 'LLVM IR file'
    bc_desc = 'LLVM BitCode file'
    fm_desc = 'Clang External Function Mapping file'
    si_desc = 'source code index file'
    Version = '2.0'
    Commit = '%REPLACE_COMMIT_INFO%'
    cc = 'clang'
    cxx = 'clang++'
    cfm = 'clang-extdef-mapping'
    fmname = 'externalFnMap.txt'
    PathTreeRoot = 'preprocess-root'
    sourcefilter = re.compile(
        r'^[^-].*\.(c|C|cc|CC|cxx|cpp|c\+\+|i|ii|ixx|ipp|i\+\+)$')
    asmfilter = re.compile(r'^[^-].*\.(s|S|sx|asm)$')
    objectfilter = re.compile(r'^[^-].*\.(o|obj)$')
    sharedfilter = re.compile(r'^[^-].*\.(so([\d.]+)?|dll)$')
    archivefilter = re.compile(r'^[^-].*\.(a|lib)$')
    libraryfilter = re.compile(r'^[^-].*\.(so([\d.]+)?|dll|a|lib)$')
    linksourcefilter = re.compile(r'^[^-].*\.(o|obj|so([\d.]+)?|dll|a|lib)$')

    # program description
    DescriptionMsg = '\n'.join(
        ['Execute compilation database dependent commands.', ''] +
        textwrap.wrap(
            'This program is used for executing commands that need the '
            'compilation flags parsed from a compilation database. Beside '
            'customized commands, it integrates the functionalities of '
            'generating the following types of files:',
            width=80, break_long_words=False, break_on_hyphens=False
        ) +
        ['\n'.join(['  - {} ({})' for _ in range(6)]).format(
            i_desc, '*.i for C files, and *.ii for C++ files',
            ast_desc, '*.ast', ll_desc, '*.ll', bc_desc, '*.bc',
            fm_desc, fmname, si_desc, '[source|ast|i|ll|bc]-index.txt'
        ), ''] +
        textwrap.wrap(
            'Besides, you can also execute other commands on some translation '
            'units. For detailed usages, please refer to the help information '
            'of the commandline arguments below.',
            width=80, break_long_words=False, break_on_hyphens=False
        )
    )
    # program version info
    VersionMsg = ''

    @staticmethod
    def getVersionMsg():
        if Default.VersionMsg:
            return Default.VersionMsg

        ret = ['Panda {} (Python 3)'.format(Default.Version),
               'git checkout: {}'.format(Default.Commit)]
        pin, pout = os.pipe()
        if 0 == os.fork():
            os.dup2(pout, 1)
            os.dup2(pout, 2)
            os.environ['LD_PRELOAD'] = Default.libpath
            os.environ['PANDA_TEMPORARY_OUTPUT_DIR'] = os.getcwd()
            openso(Default.libpath).version()
            exit(0)
        os.close(pout)
        pin = os.fdopen(pin, 'r', -1)
        while True:
            data = pin.readline()
            if not data:
                break
            ret.append(data.strip())
        Default.VersionMsg = '\n'.join(ret)
        return Default.VersionMsg

    @staticmethod
    def GetPreprocessOutputName(outputdir, OriginOutput, sufix=''):
        return os.path.normpath(os.path.join(outputdir, Default.PathTreeRoot,
                                             './' + OriginOutput + sufix))

    # }}}


# ParseArguments: parse command line arguments with argparse.
def ParseArguments(args):  # {{{
    parser = argparse.ArgumentParser(
        description=Default.DescriptionMsg,
        formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument(
        '-v', '--version', action='version', version=Default.getVersionMsg())
    parser.add_argument(
        '-V', '--verbose', action='store_true', dest='verbose',
        help='Verbose output mode.')
    parser.add_argument(
        '-b', '--build', action='store_true', dest='build',
        help='Build the project and catch the compilation database.')
    parser.add_argument(
        'commands', nargs='*',
        help=' '.join(['Command and arguments to be executed.',
                       'Add "--" before the beginning of the command.',
                       '(required when -b is enabled)']))
    parser.add_argument(
        '-A', '--generate-ast', action='store_true', dest='ast',
        help='Generate ' + Default.ast_desc)
    parser.add_argument(
        '-E', '--generate-i', action='store_true', dest='i',
        help='Generate ' + Default.i_desc)
    parser.add_argument(
        '-S', '--generate-ll', action='store_true', dest='ll',
        help='Generate ' + Default.ll_desc)
    parser.add_argument(
        '-B', '--generate-bc', action='store_true', dest='bc',
        help='Generate ' + Default.bc_desc)
    parser.add_argument(
        '-M', '--generate-fm', action='store_true', dest='fm',
        help='Generate ' + Default.fm_desc)
    parser.add_argument(
        '-L', '--list-files', action='store_true', dest='ls',
        help='Generate a list for each kind of generated files.')
    parser.add_argument(
        '-P', '--copy-file', action='store_true', dest='cp',
        help='Copy source code file to output directory.')
    parser.add_argument(
        '-T', '--target-related', action='store_true', dest='target',
        help='Generate target related compile_commands.json and file lists.')
    parser.add_argument(
        '-o', '--output', type=str, dest='output', default=Default.execdir,
        help='Customize the output directory. (default is "./")')
    parser.add_argument(
        '--compiling', metavar='<compile_commands.json>', type=str,
        dest='compiling', default=os.path.abspath('./compile_commands.json'),
        help='Customize the compiling database file.')
    parser.add_argument(
        '--linking', metavar='<link_commands.json>', type=str,
        dest='linking', default=os.path.abspath('./link_commands.json'),
        help='Customize the linking database file.')
    parser.add_argument(
        '--cc', type=str, dest='cc', default=Default.cc,
        help='Customize the C compiler. (default is clang)')
    parser.add_argument(
        '--cxx', type=str, dest='cxx', default=Default.cxx,
        help='Customize the C++ compiler. (default is clang++)')
    parser.add_argument(
        '--cfm', metavar='<clang-func-mapping>', type=str,
        dest='cfm', default=Default.cfm,
        help='Customize the function mapping scanner. (default is '
        'clang-func-mapping)')
    parser.add_argument(
        '--fm-name', metavar='<{}>'.format(Default.fmname), type=str,
        dest='fmname', default=Default.fmname,
        help='Customize the output filename of the {}. (default is {})'.format(
            Default.fm_desc, Default.fmname))
    parser.add_argument(
        '-p', '--clang-path', metavar='CLANG_PATH', type=str, dest='clang',
        help='Customize the compiler executable directory for searching.')
    parser.add_argument(
        '-j', '--jobs', type=int, dest='jobs', default=1,
        help='Customize the number of jobs allowed in parallel.')
    parser.add_argument(
        '--ctu', action='store_true', dest='ctu',
        help='Prepare for cross-TU analysis, (alias to -A and -M)')
    opts = parser.parse_args(args[1:])

    # set alias for --ctu
    if opts.ctu:
        opts.fm = True
        opts.ast = True

    if opts.build and not opts.commands:
        # -b, --build is provided without any arguments
        opts.commands = ['make']
        if opts.jobs > 1:
            opts.commands += ['-j', str(opts.jobs)]
    opts.compiling = os.path.join(Default.execdir, opts.compiling)
    opts.linking = os.path.join(Default.execdir, opts.linking)

    opts.output = os.path.abspath(opts.output)
    has_output = [opts.build, opts.ast, opts.i, opts.ll, opts.bc, opts.fm,
                  opts.ls, opts.cp]
    if not os.path.exists(opts.output) and any(has_output):
        os.makedirs(opts.output)

    # reset executable path for --clang-path
    if opts.clang:
        # If cc, cxx and cfm are set with full path, the settings will be used.
        # Otherwise, it will be merged with clang path.
        # Function os.path.join will handle this feature.
        opts.cc = os.path.abspath(os.path.join(opts.clang, opts.cc))
        opts.cxx = os.path.abspath(os.path.join(opts.clang, opts.cxx))
        opts.cfm = os.path.abspath(os.path.join(opts.clang, opts.cfm))
    CC1JsonFilter.setCompilers(opts.cc, opts.cxx)

    # check whether the command executable exists and is executable
    def checkCommandExecutable(cmd, opt):
        try:
            popen([cmd, '--version'], stdout=pipe, stderr=pipe).wait()
        except OSError as err:
            print(
                '\n'.join([
                    'Error:\tRequired tool "{}" not available.',
                    '\tPlease check your settings of "{}" or "--clang-path".',
                    'popen: {}']).format(
                    os.path.basename(cmd), opt, err),
                file=sys.stderr)
            exit(err.errno)

    if opts.fm:
        checkCommandExecutable(opts.cfm, '--cfm')
    if opts.ast or opts.i or opts.ll or opts.bc:
        checkCommandExecutable(opts.cc, '--cc')
        checkCommandExecutable(opts.cxx, '--cxx')

    return opts

    # }}}


# RunCommand: run the command to do the preprocess
#
#   command: the command object to be executed. (in the parsed JSON format)
#   verbose: dump the command to be executed.
def RunCommand(command, verbose):
    print('Generating "' + command.output + '"')

    arguments = command.arguments
    outputDir = os.path.dirname(command.output)

    if verbose:
        print(command)

    # create directory for output file
    while not os.path.exists(outputDir):
        try:
            os.makedirs(outputDir)
        except FileExistsError:  # may happen when multi-thread
            pass

    process = popen(arguments, cwd=command.directory)
    process.wait()


# TargetJob: the job of every link target.
#
#   opts: opts object (refer to ParseArguments)
#   cdb: the compilation database struct
#   target: the filename of the link target
#   dependencies: the files that the target depends on
#   - keep target=None and dependencies=[] if the job is for target `all'
def TargetJob(opts, cdb, target=None, dependencies=[]):
    outputDB = None
    outputdir = opts.output
    if target:
        print('Generating "compile_commands.json" for target "{}".'
              .format(target))
        outputdir = Default.GetPreprocessOutputName(outputdir, target)
        if not os.path.exists(outputdir):
            os.makedirs(outputdir)
        output = os.path.join(outputdir, 'compile_commands.json')
        outputDB = [cdb[i] for i in dependencies]
        json.dump([i.compilation for i in outputDB],
                  open(output, 'w'), indent=4)
    else:
        outputDB = [cdb[i] for i in cdb]
    srclist = {src for t in outputDB for src in t.files}
    if opts.fm:
        print('Generating function mapping list for {}.'.format(
            'target "{}"'.format(target) if target else 'the project'))
        arguments = [opts.cfm, '-p', Default.execdir] + list(srclist)
        if opts.verbose:
            print(arguments)
        process = popen(arguments, cwd=outputdir, stdout=pipe, stderr=pipe)
        fms = process.stdout.read().decode('utf-8').strip('\n').split('\n')
        process.wait()
        with open(os.path.join(outputdir, opts.fmname), 'w') as ffm:
            for func in fms:
                func = func.split()
                if func:
                    print(func[0], Default.GetPreprocessOutputName(
                        opts.output, func[1], '.ast'), file=ffm)
    if opts.ls:
        print('Generating file lists for {}.'.format(
            'target "{}"'.format(target) if target else 'the project'))
        with open(os.path.join(outputdir, 'source-index.txt'), 'w') as fsrc:
            for i in srclist:
                print(i, file=fsrc)
        fast = open(os.path.join(outputdir, 'ast-index.txt')
                    if opts.ast else os.devnull, 'w')
        fi = open(os.path.join(outputdir, 'i-index.txt')
                  if opts.i else os.devnull, 'w')
        fll = open(os.path.join(outputdir, 'll-index.txt')
                   if opts.ll else os.devnull, 'w')
        fbc = open(os.path.join(outputdir, 'bc-index.txt')
                   if opts.bc else os.devnull, 'w')
        for t in outputDB:
            print(
                Default.GetPreprocessOutputName(opts.output, t.output, '.ast'),
                file=fast)
            print(
                Default.GetPreprocessOutputName(
                    opts.output,
                    t.output,
                    '.i' if t.compiler == opts.cc else '.ii'),
                file=fi)
            print(
                Default.GetPreprocessOutputName(opts.output, t.output, '.ll'),
                file=fll)
            print(
                Default.GetPreprocessOutputName(opts.output, t.output, '.bc'),
                file=fbc)
        for f in (fast, fi, fll, fbc):
            f.close()


# threadjob: Execute func with args and return its return value.
def threadjob(func, *args):
    return func(*args)


# PreprocessProject: monitor and control the process of preprocess
#
#   opts: opts object (refer to ParseArguments)
#   cdb: compiling commands
#   ldb: linking commands
def PreprocessProject(opts, cdb, ldb):
    if not cdb:
        return

    jobList = list()

    # Traverse compliation database, create job for each TU.
    def MakePreprocessJob():
        projectfiles = set()

        def MakeExecutedCommandForOneJob(job):
            directory = job.directory
            arguments = [job.compiler] + job.arguments

            # make command for ast/i/ll/bc job
            def MakeExecutedCommand(ext, appendargs):
                out = Default.GetPreprocessOutputName(
                    opts.output, job.output, ext)
                args = arguments + appendargs
                args[job.oindex + 1] = out
                jobList.append((RunCommand, ExecutedCommand(
                    output=out, arguments=args, directory=directory),
                    opts.verbose))
            if opts.ast:
                MakeExecutedCommand('.ast', ['-emit-ast'])
            if opts.i:
                MakeExecutedCommand('.i' if job.compiler == opts.cc else '.ii',
                                    ['-E'])
            if opts.ll:
                MakeExecutedCommand(
                    '.ll', [
                        '-emit-llvm', '-S', '-Xclang', '-disable-O0-optnone'])
            if opts.bc:
                MakeExecutedCommand(
                    '.bc', [
                        '-emit-llvm', '-Xclang', '-disable-O0-optnone'])

            # only collect depended files of current TU, job are generated
            # below
            if opts.cp:
                print('Collecting dependencies for target "{}".'.format(
                    job.output))
                args = [job.compiler] + job.arguments
                # replace -o (rather than output) with -MT, and -c with -MM
                args[job.oindex] = '-MT'
                args[args.index('-c')] = '-MM'
                if opts.verbose:
                    print(args)
                p = popen(args, cwd=directory, stdout=pipe, stderr=pipe)
                for dependency in p.stdout.read().decode('utf-8').split()[1:]:
                    if dependency != '\\':
                        dependency = os.path.join(directory, dependency)
                        projectfiles.add(dependency)
                p.wait()

        # MakePreprocessJob:
        for originOutput in cdb:
            job = cdb[originOutput]
            MakeExecutedCommandForOneJob(job)
        for i in projectfiles:
            oi = Default.GetPreprocessOutputName(opts.output, i)
            jobList.append(
                (RunCommand,
                 ExecutedCommand(
                     output=oi,
                     arguments=['cp', i, oi],
                     directory=Default.execdir),
                    opts.verbose))

    # Generate pre-process file list
    MakePreprocessJob()

    # Generate target-related compile_commands
    dependency = dict()

    # Traverse linking database, create job for each link target.
    def DeductTargets():
        if not ldb:
            return

        def DeductOneTarget(target):
            if target.output not in dependency:
                dependency[target.output] = target.objects.copy()
                if target.libraries:
                    for lib in target.libraries:
                        dependency[target.output] += DeductOneTarget(ldb[lib])
            return dependency[target.output]
        for tout in ldb:
            DeductOneTarget(ldb[tout])

    if opts.target:
        DeductTargets()
        for t in dependency:
            jobList.append((TargetJob, opts, cdb, t, dependency[t]))

    # TargetJob for all the source files
    jobList.append((TargetJob, opts, cdb))

    # Do parallel job:
    if 1 == opts.jobs:
        for i in jobList:
            threadjob(*i)
    else:
        with pool(opts.jobs) as p:
            p.starmap(threadjob, jobList)


class Filter:
    FilterType = namedtuple(
        'FilterType', [
            'execfilter', 'abort', 'remove', 'output', 'source'])
    ParameterType = namedtuple('ParameterType', ['matcher', 'count'])

    def __init__(self, filters):
        self.filters = filters
        self.exe = None
        self.files = None
        self.arguments = None
        self.output = None

    @staticmethod
    def MatchParameter(matcher, count, arg, i):
        match = matcher.match(arg)
        if not match:
            return None
        ret = [match.group(0)]
        if match.group(0) != arg:
            ret.append(arg[match.end():])
            count -= 1
        for _ in range(count):
            ret.append(next(i))
        return ret

    def MatchExecFilterIndex(self, exe):
        exe = os.path.basename(exe)
        for efi in range(len(self.filters.execfilter)):
            if self.filters.execfilter[efi].fullmatch(exe):
                return efi
        return None

    def MatchExec(self, exe):
        return exe if self.MatchExecFilterIndex(exe) is not None else None

    def MatchAbort(self, arg):
        return arg in self.filters.abort

    def MatchRemove(self, arg, i):
        for rm in self.filters.remove:
            match = Filter.MatchParameter(rm.matcher, rm.count, arg, i)
            if match:
                return True
        return False

    def MatchOutput(self, arg, i):
        return Filter.MatchParameter(self.filters.output.matcher,
                                     self.filters.output.count, arg, i)

    def MatchSource(self, arg, pwd):
        arg = os.path.join(pwd, arg)
        match = self.filters.source.match(os.path.basename(arg))
        if match and (os.path.exists(arg) or arg.startswith('/tmp/')):
            return arg
        else:
            return None

    def ParseExecutionCommands(self, arguments, pwd):
        args = iter(arguments)
        self.exe = self.MatchExec(next(args))
        if not self.exe:
            return None
        self.pwd = pwd
        self.files = list()
        self.arguments = list()
        self.output = None
        for arg in args:
            if self.filters.abort and self.MatchAbort(arg):
                return None
            if not self.filters.remove or not self.MatchRemove(arg, args):
                if self.filters.output:
                    target = self.MatchOutput(arg, args)
                    if target:
                        self.output = os.path.join(pwd, target[-1])
                        if 1 != len(target):
                            self.arguments += target[:-1]
                        self.arguments.append(self.output)
                        continue
                if self.filters.source:
                    src = self.MatchSource(arg, pwd)
                    if src:
                        self.files.append(src)
                        self.arguments.append(src)
                        continue
                # finally: add all un-matched arguments
                self.arguments.append(arg)
        return (self.exe, self.pwd, self.files, self.arguments, self.output,
                self.arguments.index(self.output) if self.output else None)


class CC1Filter(Filter):
    cc1filter = [
        re.compile(r'^([\w-]*g?cc|[\w-]*[gc]\+\+|clang(\+\+)?)(-[\d.]+)?$')]
    cc1abort = ['-E', '-cc1', '-cc1as', '-M', '-MM', '-###', '-fsyntax-only']
    cc1remove = [Filter.ParameterType(re.compile(r'^-[lL]'), 1),
                 Filter.ParameterType(re.compile(r'^-M[TF]$'), 1),
                 Filter.ParameterType(re.compile(r'^-(Wl,|shared|static)'), 0),
                 Filter.ParameterType(re.compile(
                     r'^-(v|Werror(=.+)?|Wall|Wextra|M[DGMPQ]*|)$'), 0)]
    cc1output = Filter.ParameterType(re.compile(r'^-o'), 1)
    cc1source = Default.sourcefilter

    def __init__(self):
        super().__init__(Filter.FilterType(
            execfilter=CC1Filter.cc1filter, abort=CC1Filter.cc1abort,
            remove=CC1Filter.cc1remove, output=CC1Filter.cc1output,
            source=CC1Filter.cc1source))

    @staticmethod
    def MatchArguments(arguments, pwd):
        Self = CC1Filter()
        result = Self.ParseExecutionCommands(arguments, pwd)
        return CompilingCommands(
            compiler=result[0],
            directory=result[1],
            files=result[2],
            arguments=result[3],
            output=result[4],
            oindex=result[5],
            compilation='-c' in result[3]) if result else None

    @staticmethod
    def getTargetID(name):
        return ''.join([os.path.dirname(name)[-1],
                        '.', os.path.basename(name)])

    @staticmethod
    def reformatInputFile(ifile, arguments, files, compilation):
        for rm in files:
            if rm == ifile:
                if not compilation:
                    arguments.insert(arguments.index(ifile), '-c')
            else:
                arguments.remove(rm)


class ARFilter(Filter):
    arfilter = [re.compile(r'^[\w-]*ar(-[\d.]+)?$')]
    aroutput = Default.archivefilter
    arsource = Default.objectfilter

    def __init__(self):
        super().__init__(Filter.FilterType(
            execfilter=ARFilter.arfilter, abort=None, remove=None,
            output=ARFilter.aroutput, source=ARFilter.arsource))

    def MatchOutput(self, arg, i):
        return [arg] if self.filters.output.match(arg) else None

    @staticmethod
    def MatchArguments(arguments, pwd):
        Self = ARFilter()
        result = Self.ParseExecutionCommands(arguments, pwd)
        return LinkingCommands(
            linker=result[0],
            directory=result[1],
            files=result[2],
            arguments=result[3],
            output=result[4],
            oindex=result[5],
            archive=True) if result else None


class LDFilter(Filter):
    ldfilter = [re.compile(r'^[\w-]*ld(-[\d.]+)?$')]
    ldoutput = Filter.ParameterType(re.compile(r'^-o'), 1)
    ldsource = Default.linksourcefilter

    def __init__(self):
        super().__init__(Filter.FilterType(
            execfilter=LDFilter.ldfilter, abort=None, remove=None,
            output=LDFilter.ldoutput, source=LDFilter.ldsource))

    @staticmethod
    def MatchArguments(arguments, pwd):
        Self = LDFilter()
        result = Self.ParseExecutionCommands(arguments, pwd)
        return LinkingCommands(
            linker=result[0],
            directory=result[1],
            files=result[2],
            arguments=result[3],
            output=result[4],
            oindex=result[5],
            archive=False) if result else None


class AliasFilter:
    AliasFilterType = namedtuple('AliasFilterType', ['exe', 'input', 'output'])
    clangfilter = AliasFilterType(
        re.compile(r'^clang(-[\d.]+)?$'),
        re.compile(r'^-main-file-name$'),
        re.compile(r'^-o'))
    cc1filter = AliasFilterType(re.compile(r'^[\w-]*cc1(plus)?(-[\d.]+)?$'),
                                re.compile(r'^-dumpbase$'), re.compile(r'^-o'))
    asfilter = AliasFilterType(re.compile(r'^[\w-]*as(-[\d.]+)?$'),
                               Default.asmfilter, re.compile(r'^-o'))

    @staticmethod
    def MatchArguments(arguments, pwd):
        argfilter, ifile, ofile = None, None, None
        args = iter(arguments)
        exename = os.path.basename(next(args))
        if AliasFilter.clangfilter.exe.match(exename) and '-cc1' == next(args):
            argfilter = AliasFilter.clangfilter
        elif AliasFilter.cc1filter.exe.match(exename):
            argfilter = AliasFilter.cc1filter
        elif AliasFilter.asfilter.exe.match(exename):
            argfilter = AliasFilter.asfilter
        if not argfilter:
            return None
        for i in args:
            imatch = argfilter.input.match(i)
            omatch = argfilter.output.match(i)
            if imatch:
                ifile = next(args) if '-' == imatch.group(0)[0] \
                    else imatch.group(0)
            elif omatch:
                ofile = next(args) if '-' == omatch.group(0)[0] \
                    else omatch.group(0)
        return {os.path.join(pwd, ifile): [os.path.join(pwd, ofile)]} \
            if ifile and ofile else None


def CatchCompilationDatabase(opts):
    def BuildProject(opts):
        print('Compiling the project: ' + ' '.join(opts.commands))
        outputdir = os.path.abspath(
            os.path.join(
                opts.output,
                time.strftime(
                    '%Y%m%d_%H%M%S.build',
                    time.localtime())))
        os.makedirs(outputdir)

        environ = os.environ.copy()
        environ['LD_PRELOAD'] = Default.libpath
        environ['PANDA_TEMPORARY_OUTPUT_DIR'] = outputdir
        if opts.verbose:
            print(opts.commands)
        popen(opts.commands, env=environ).wait()

        return outputdir

    def SimplifyAlias(AD):
        ret = dict()
        for src in AD:
            if Default.sourcefilter.match(src):
                ret[src] = list()
                for value in AD[src]:
                    if not Default.objectfilter.match(value):
                        value = AD[value].pop()
                    if value.startswith('/tmp/'):
                        ret[value] = src + '.' + os.path.basename(value)
                        value = ret[value]
                    else:
                        ret[value] = value
                    ret[src].append(value)
            elif not Default.asmfilter.match(src):
                ret[src] = AD[src]
        return ret

    def ConstructCompilationDatabase(CD, AD):
        ret = list()
        for cmd in CD:
            for ifile in cmd.files:
                arguments = [cmd.compiler] + cmd.arguments
                output = AD[cmd.output]
                if isinstance(output, list):
                    for out in AD[cmd.output]:
                        if out in AD and AD[out] in AD[ifile]:
                            output = AD[out]
                            break
                arguments[cmd.oindex + 1] = output
                CC1Filter.reformatInputFile(ifile, arguments, cmd.files,
                                            cmd.compilation)
                ret.append({'output': output, 'directory': cmd.directory,
                            'file': ifile, 'arguments': arguments})
        with open(os.path.join(opts.output, 'compile_commands.json'), 'w') \
                as f:
            json.dump(ret, f, indent=4)
        return ret

    def ConstructLinkingDatabase(LD, AD):
        ret = list()
        for cmd in LD:
            objs, archs, sobjs = list(), list(), list()
            for ifile in cmd.files.copy():
                if ifile in AD:
                    if Default.objectfilter.match(ifile):
                        objs.append(AD[ifile])
                        cmd.arguments[cmd.arguments.index(ifile)] = AD[ifile]
                        cmd.files[cmd.files.index(ifile)] = AD[ifile]
                    elif Default.sharedfilter.match(ifile):
                        sobjs.append(ifile)
                    else:
                        archs.append(ifile)
                else:
                    cmd.files.remove(ifile)
            if not objs and not archs and not sobjs:
                continue
            lo = {'output': cmd.output, 'directory': cmd.directory,
                  'arguments': [cmd.linker] + cmd.arguments}
            if objs:
                lo['objects'] = objs
            if archs:
                lo['archives'] = archs
            if sobjs:
                lo['shareds'] = sobjs
            ret.append(lo)
        with open(os.path.join(opts.output, 'link_commands.json'), 'w') as f:
            json.dump(ret, f, indent=4)
        return ret

    def HandleCompileCommands(outputdir):
        def TraverseCommands(outputdir):
            for outputdir, _, files in os.walk(outputdir):
                for i in files:
                    i = os.path.join(outputdir, i)
                    yield json.load(open(i, 'r'))

        print('Generating "compile_commands.json" and "link_commands.json".')
        CompilationDatabase = list()
        LinkingDatabase = list()
        AliasDatabase = dict()
        for i in TraverseCommands(outputdir):
            exe = ExecCommands(**i)
            cd = CC1Filter.MatchArguments(exe.arguments, exe.pwd)
            if cd and cd.files:
                CompilationDatabase.append(cd)
                continue
            ar = ARFilter.MatchArguments(exe.arguments, exe.pwd)
            if ar and ar.files:
                LinkingDatabase.append(ar)
                AliasDatabase[ar.output] = ar.files
                continue
            ld = LDFilter.MatchArguments(exe.arguments, exe.pwd)
            if ld and ld.files:
                LinkingDatabase.append(ld)
                AliasDatabase[ld.output] = ld.files
                continue
            al = AliasFilter.MatchArguments(exe.arguments, exe.pwd)
            if al:
                for k in al:
                    if k in AliasDatabase:
                        AliasDatabase[k] += al[k]
                    else:
                        AliasDatabase[k] = al[k]
                continue
        AliasDatabase = SimplifyAlias(AliasDatabase)
        CDJson = ConstructCompilationDatabase(
            CompilationDatabase, AliasDatabase)
        LDJson = ConstructLinkingDatabase(LinkingDatabase, AliasDatabase)
        with open(os.path.join(outputdir, 'name_mapping.json'), 'w') as f:
            json.dump(AliasDatabase, f, indent=4)
        return (CDJson, LDJson)

    # CatchCompilationDatabase:
    return HandleCompileCommands(BuildProject(opts))


class CC1JsonFilter(Filter):
    cc1filter = [re.compile(r'^([\w-]*g?cc|clang)(-[\d.]+)?$'),
                 re.compile(r'^([\w-]*[gc]\+\+|clang\+\+)(-[\d.]+)?$')]
    cc1compiler = [Default.cc, Default.cxx]

    cc1remove = CC1Filter.cc1remove + [
        Filter.ParameterType(re.compile(r'^-(w|g|O([0123sg]|fast)?)$'), 0)]

    cc1append = ['-w', '-g', '-O0']

    @staticmethod
    def setCompilers(cc, cxx):
        CC1JsonFilter.cc1compiler = [cc, cxx]

    def __init__(self):
        super().__init__(Filter.FilterType(
            execfilter=CC1JsonFilter.cc1filter, abort=CC1Filter.cc1abort,
            remove=CC1JsonFilter.cc1remove, output=CC1Filter.cc1output,
            source=CC1Filter.cc1source))

    def MatchExec(self, exe):
        index = self.MatchExecFilterIndex(exe)
        return None if index is None else CC1JsonFilter.cc1compiler[index]

    @staticmethod
    def MatchArguments(job):
        Self = CC1JsonFilter()
        result = Self.ParseExecutionCommands(
            job['arguments'], job['directory'])
        output = result[4]
        if not Default.objectfilter.match(output):
            target = CC1Filter.getTargetID(output)
            output = ''.join([job['file'], '.', target, '.o'])
            result[3][result[5]] = output
        return CompilingCommands(compiler=result[0], directory=result[1],
                                 files=result[2], arguments=result[3] +
                                 CC1JsonFilter.cc1append,
                                 output=output, oindex=result[5],
                                 # Different with CC1Filter, CC1JsonFilter
                                 # will fill compilation field with the
                                 # original CompilingCommands.
                                 compilation=job) \
            if result else None

    @staticmethod
    def getCompilerType(name):
        Self = CC1Filter()
        return Self.MatchExec(name)


# ParseCompilationCommands: parse the database objects
#
#   opts: opts object (refer to ParseArguments)
def ParseCompilationCommands(CDList, LDList):
    def ParseCDList(CDList):
        if not CDList:
            return None
        cdret = dict()
        for job in CDList:
            # convert 'command' to 'arguments'
            if 'command' in job:
                job['arguments'] = shlex.split(job.pop('command'))
            job['file'] = os.path.join(job['directory'], job['file'])
            parsed = CC1JsonFilter.MatchArguments(job)
            CC1Filter.reformatInputFile(
                job['file'],
                parsed.arguments,
                parsed.files,
                '-c' in parsed.arguments)
            cdret[parsed.output] = parsed
        return cdret

    def ParseLDList(LDList):
        if not LDList:
            return None
        ldret = dict()
        for job in LDList:
            if 'command' in job:
                job['arguments'] = shlex.split(job.pop('command'))
            job['output'] = os.path.join(job['directory'], job['output'])

            def joinDirectory(job, item):
                if item in job:
                    for i in range(len(job[item])):
                        job[item][i] = os.path.join(
                            job['directory'], job[item][i])
            joinDirectory(job, 'objects')
            joinDirectory(job, 'archives')
            joinDirectory(job, 'shareds')
            ldret[job['output']] = LinkingAlias(
                output=job['output'], objects=job['objects'],
                libraries=(job['archives'] if 'archives' in job else [] +
                           job['shareds'] if 'shareds' in job else []))
        return ldret

    return ParseCDList(CDList), ParseLDList(LDList)


def main(args):
    opts = ParseArguments(args)
    cj, lj = None, None
    if opts.build:
        cj, lj = CatchCompilationDatabase(opts)
    else:
        try:
            cj = json.load(open(opts.compiling, 'r'))
            # workaround for linking database unsupported projects
            if os.path.isfile(opts.linking):
                lj = json.load(open(opts.linking, 'r'))
            else:
                print(
                    'Warning: Processing compilation database without linking '
                    'information for linking database.',
                    file=sys.stderr)
        except OSError as err:
            print(
                'Error while openning file: open: {}'.format(err),
                file=sys.stderr)
            exit(err.errno)
    cd, ld = ParseCompilationCommands(cj, lj)
    PreprocessProject(opts, cd, ld)


if '__main__' == __name__:
    main(sys.argv)
