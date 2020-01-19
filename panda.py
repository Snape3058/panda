#!/usr/bin/env python3

import os
import sys
import json
import threadpool
import argparse
from subprocess import Popen as popen
from subprocess import PIPE as pipe
import re
import shlex
from ctypes import CDLL as openso
import time
from collections import namedtuple
import textwrap

ExecCommands = namedtuple('ExecCommands',
        ['method', 'ppid', 'pid', 'pwd', 'arguments'])
CompilingCommands = namedtuple('CompilingCommands',
        ['compiler', 'directory', 'files', 'arguments', 'output', 'oindex', 'compilation'])
LinkingCommands = namedtuple('LinkingCommands',
        ['linker', 'directory', 'files', 'arguments', 'output', 'oindex', 'archive'])


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
    filterstr = [
            '-o:',
            '-O([0123sg]|fast)?',
            '-Werror(=.+)?',
            '-W(all|extra)?',
            '-fsyntax-only',
            '-g',
            '.+\\.o(bj)?',
            ]
    Version = '2.0'
    Commit = '%REPLACE_COMMIT_INFO%'
    cc = 'clang'
    cxx = 'clang++'
    cfm = 'clang-extdef-mapping'
    fmname = 'externalFnMap.txt'
    sourcefilter = re.compile('^[^-].*\.(c|C|cc|CC|cxx|cpp|c\+\+|i|ii|ixx|ipp|i\+\+)')
    asmfilter = re.compile("^[^-].*\.(s|S|sx|asm)$")
    objectfilter = re.compile('^[^-].*\.(o|obj)$')
    sharedfilter = re.compile('^[^-].*\.(so([\d.]+)?|dll)$')
    archivefilter = re.compile('^[^-].*\.(a|lib)$')
    libraryfilter = re.compile('^[^-].*\.(so([\d.]+)?|dll|a|lib)$')
    linksourcefilter = re.compile('^[^-].*\.(o|obj|so([\d.]+)?|dll|a|lib)$')

    # program description
    DescriptionMsg = '\n'.join(
            ['Execute compilation database dependent commands.', ''] +
            textwrap.wrap(
'''This program is used for executing commands that need the compilation flags
parsed from a compilation database. Beside customized commands, it integrates
the functionalities of generating the following types of files:''',
                width=80, break_long_words=False, break_on_hyphens=False
                ) +
            ['\n'.join(['  - {} ({})' for _ in range(6)]).format(
                    i_desc, '*.i for C files, and *.ii for C++ files',
                    ast_desc, '*.ast', ll_desc, '*.ll', bc_desc, '*.bc',
                    fm_desc, fmname, si_desc, '[source|ast|i|ll|bc]-index.txt'
                    ), ''] +
            textwrap.wrap(
'''Besides, you can also execute other commands on some translation units. For
detailed usages, please refer to the help information of the commandline
arguments below.''',
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

    # }}}


# ParseArguments: parse command line arguments with argparse.
def ParseArguments(args):  # {{{
    parser = argparse.ArgumentParser(description=Default.DescriptionMsg,
            formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('-v', '--version', action='version',
            version=Default.getVersionMsg())
    parser.add_argument('-V', '--verbose', action='store_true', dest='verbose',
            help='Verbose output mode.')
    parser.add_argument('-b', '--build', action='store_true', dest='build',
            help='Build the project and catch the compilation database.')
    parser.add_argument('commands', nargs='*',
            help=' '.join(['Command and arguments to be executed.',
                'Add "--" before the beginning of the command.',
                '(required when -b is enabled)']))
    parser.add_argument('-A', '--generate-ast', action='store_true', dest='ast',
            help='Generate ' + Default.ast_desc)
    parser.add_argument('-E', '--generate-i', action='store_true', dest='i',
            help='Generate ' + Default.i_desc)
    parser.add_argument('-S', '--generate-ll', action='store_true', dest='ll',
            help='Generate ' + Default.ll_desc)
    parser.add_argument('-B', '--generate-bc', action='store_true', dest='bc',
            help='Generate ' + Default.bc_desc)
    parser.add_argument('-M', '--generate-fm', action='store_true', dest='fm',
            help='Generate ' + Default.fm_desc)
    parser.add_argument('-L', '--list-files', action='store_true', dest='ls',
            help='List source code files and generated files to different index files.')
    parser.add_argument('-P', '--copy-file', action='store_true', dest='cp',
            help='Copy source code file to output directory.')
    parser.add_argument('-o', '--output',
            type=str, dest='output', default=os.path.abspath('./'),
            help='Customize the output directory. (default is "./")')
    parser.add_argument('--compiling', metavar='<compile_commands.json>',
            type=str, dest='compiling', default=os.path.abspath('./compile_commands.json'),
            help='Customize the compiling database file.')
    parser.add_argument('--cc',
            type=str, dest='cc', default=Default.cc,
            help='Customize the C compiler. (default is clang)')
    parser.add_argument('--cxx',
            type=str, dest='cxx', default=Default.cxx,
            help='Customize the C++ compiler. (default is clang++)')
    parser.add_argument('--cfm', metavar='<clang-func-mapping>',
            type=str, dest='cfm', default=Default.cfm,
            help='Customize the function mapping scanner. (default is clang-func-mapping)')
    parser.add_argument('--fm-name', metavar='<{}>'.format(Default.fmname),
            type=str, dest='fmname', default=Default.fmname,
            help='Customize the output filename of the {}. (default is {})'.format(
                Default.fm_desc, Default.fmname))
    parser.add_argument('-p', '--clang-path', metavar='CLANG_PATH', type=str, dest='clang',
            help='Customize the Clang executable directory for searching compilers.')
    parser.add_argument('-j', '--jobs', type=int, dest='jobs', default=1,
            help='Customize the number of jobs allowed in parallel.')
    parser.add_argument('--ctu', action='store_true', dest='ctu',
            help='Prepare for cross-TU analysis, (alias to -A and -M)')
    opts = parser.parse_args(args[1:])

    # set alias for --ctu
    if opts.ctu:
        opts.fm = True
        opts.ast = True

    if opts.build and not opts.commands:
        # -b, --build is provided without any arguments
        opts.commands = ['make']

    opts.output = os.path.abspath(opts.output)
    if not os.path.exists(opts.output) and (opts.build or opts.ast or opts.i or
            opts.ll or opts.bc or opts.fm or opts.ls or opts.cp):
        os.makedirs(opts.output)

    return opts

    # reset executable path for --clang-path
    if opts.clang:
        # If cc, cxx and cfm are set with full path, the settings will be used.
        # Otherwise, it will be merged with clang path.
        # Function os.path.join will handle this feature.
        opts.cc = os.path.abspath(os.path.join(opts.clang, opts.cc))
        opts.cxx = os.path.abspath(os.path.join(opts.clang, opts.cxx))
        opts.cfm = os.path.abspath(os.path.join(opts.clang, opts.cfm))

    # check whether the command executable exists and is executable
    def isCommandExecutable(cmd, opt):
        try:
            popen([cmd, '--version'], stdout=pipe, stderr=pipe).wait()
        except (FileNotFoundError, PermissionError) as err:
            print('\n'.join(['Error:\tRequired tool "{}" not available.',
                '\tPlease check your settings of "{}" or "--clang-path".',
                'popen: {}']).format(
                    os.path.basename(cmd), opt, err),
                file=sys.stderr)
            return False
        return True

    if opts.fm:
        if not isCommandExecutable(opts.cfm, '--cfm'):
            exit(1)
    if opts.ast or opts.i or opts.ll or opts.bc:
        if not isCommandExecutable(opts.cc, '--cc') or \
                not isCommandExecutable(opts.cxx, '--cxx'):
            exit(1)

    # }}}


# GetSourceFile: find out source file path through command object
#
#   command: a compile command object in database
def GetSourceFile(command):
    return os.path.abspath(os.path.join(command['directory'], command['file']))


# GetCompilerAndExtension: generate the preprocessor compiler
#                          and corresponding extension name.
#
#   opts: opts object (refer to ParseArguments)
#   compiler: compiler name
#   extension: list of extension names for [cc, cxx]
def GetCompilerAndExtension(opts, compiler, extension):
    # check suffix only as the compiler argument can be full path
    if 'cc' == compiler[-2:] or 'clang' == compiler[-5:]:
        return opts.cc, extension[0]
    elif '++' == compiler[-2:]:
        return opts.cxx, extension[1]
    else:
        assert False, 'What is this compiler? ' + compiler


# GetOutputName: generate the filename of the preprocessed file.
#
#   outputDir: output directory
#   command: a compile command object in database
#   extension: the extension name of the preprocessed file
def GetOutputName(outputDir, command, extension):
    return os.path.abspath(os.path.join(outputDir,
        GetSourceFile(command)[1:]) + '.' + extension)


# MakeCommand: replace the arguments with correct value for preprocess
#
#   opts: opts object (refer to ParseArguments)
#   command: the command object parsed from JSON
#   extension: the suffix representing its file type
#   prefix, suffix: the additional arguments to do the corresponding preprocess
#   argfilter: function to filter arguments
#
#   return: command object
#       the command object is defined as follows:
#           - arguments: list of arguments to be executed by compiler
#           - directory: compiler working directory
#           - output: directory of -o parameter
def MakeCommand(opts, command, extension, prefix, suffix, argfilter):
    compiler, extension = GetCompilerAndExtension(
            opts, command['arguments'][0], extension)
    arguments = [compiler]

    # append additional arguments for generating targets
    arguments += prefix

    # generate arguments (including the source file)
    # FIXME: when generating with both source files and object files,
    #        if object files are not available, clang will report 404.
    #        Currently, a filter is added to remove all .o or .obj files.
    arguments += argfilter(command['arguments'][1:])

    # generate the full path of output file with file type extension
    output = GetOutputName(opts.output, command, extension)
    arguments += ['-o', output]

    # append additional arguments for generating targets
    arguments += suffix

    return {'directory': command['directory'],
            'arguments': arguments,
            'output': output}


# MakeCopyCommand: make command for copy operation.
#
#   opts: opts object (refer to ParseArguments)
#   command: the command object parsed from JSON
#
#   return: command object of cp $file $output/$directory/$file
def MakeCopyCommand(opts, command):
    src = GetSourceFile(command)
    output = os.path.abspath(os.path.join(opts.output, src[1:]))

    return {'directory': command['directory'],
            'arguments': ['cp', src, output],
            'output': output}


# RunCommand: run the command to do the preprocess
#
#   command: the command object to be executed. (in the parsed JSON format)
#   verbose: dump the command to be executed.
def RunCommand(command, verbose):
    print('Generating "' + command['output'] + '"')

    arguments = command['arguments']
    outputDir = os.path.dirname(command['output'])

    if verbose:
        print(arguments)

    # create directory for output file
    if not os.path.exists(outputDir):
        try:
            os.makedirs(outputDir)
        except FileExistsError:  # may happen when multi-thread
            pass

    process = popen(arguments, cwd=command['directory'])
    process.wait()


# GenerateFunctionMappingList: invoke clang-func-mapping to
#   generate externalFnMap.txt
#
#   opts: opts object (refer to ParseArguments)
#   jobs: the compilation database
def GenerateFunctionMappingList(opts, jobs):
    print('Generating function mapping list.')

    src = [GetSourceFile(i) for i in jobs]
    path = os.path.dirname(opts.compiling)
    arguments = [opts.cfm, '-p', path] + src
    outfile = os.path.join(opts.output, opts.fmname)

    process = popen(arguments, stdout=pipe, stderr=pipe)
    (out, err) = process.communicate()
    fm = out.decode('utf-8').replace(' /', ' ').replace('\n', '.ast\n')

    with open(outfile, 'w') as fout:
        fout.write(fm)

    process.wait()


# GenerateSourceFileList: dump all TU to an index file.
#
#   opts: opts object (refer to ParseArguments)
#   jobs: the compilation database
def GenerateSourceFileList(opts, jobs):
    def WriteListToFile(name, index):
        name = os.path.abspath(os.path.join(opts.output, name))
        print('Generating "{}".'.format(name))

        with open(name, 'w') as fout:
            for i in index:
                fout.write(i)
                fout.write('\n')

    WriteListToFile('source-index.txt', [GetSourceFile(i) for i in jobs])

    def WriteGeneratedFileListToFile(name, extension):
        WriteListToFile(name + '-index.txt',
                [GetOutputName(opts.output, i,
                    GetCompilerAndExtension(opts, i['arguments'][0], extension)[1])
                    for i in jobs])
    if opts.ast:
        WriteGeneratedFileListToFile('ast', ['ast', 'ast'])
    if opts.i:
        WriteGeneratedFileListToFile('i', ['i', 'ii'])
    if opts.ll:
        WriteGeneratedFileListToFile('ll', ['ll', 'll'])
    if opts.bc:
        WriteGeneratedFileListToFile('bc', ['bc', 'bc'])


# PreprocessProject: monitor and control the process of preprocess
#
#   opts: opts object (refer to ParseArguments)
#   jobList: compile commands
def PreprocessProject(opts, jobList):
    def jobRun(opts, job):  # {{{
        commands = []

        # compile filter regexp and return a filter of it
        #   filterstr: a list of filter strings
        def getArgFilter(filterstr):  # {{{
            # create filter
            filters = []

            for fs in filterstr:
                if ':' == fs[-1]:
                    filters.append((re.compile(fs[:-1]), True))
                else:
                    filters.append((re.compile(fs), False))

            def ArgFilter(argv):
                ret = []

                I = iter(argv)
                while True:
                    A = next(I, None)
                    if A is None:
                        break

                    for f in filters:
                        # remove matched
                        if f[0].fullmatch(A):
                            if f[1]:
                                next(I)
                            A = None
                            break

                    if A:
                        ret.append(A)

                return ret

            return ArgFilter
            # }}}

        # jobRun:
        if opts.ast:
            commands.append(MakeCommand(
                opts, job, ['ast', 'ast'], ['-emit-ast'], ['-w'],
                getArgFilter(Default.filterstr)))

        if opts.i:
            commands.append(MakeCommand(
                opts, job, ['i', 'ii'], ['-E'], ['-w'],
                getArgFilter(Default.filterstr)))

        if opts.ll:
            commands.append(MakeCommand(
                opts, job, ['ll', 'll'], ['-c', '-g', '-emit-llvm', '-S'], ['-w'],
                getArgFilter(Default.filterstr)))

        if opts.bc:
            commands.append(MakeCommand(
                opts, job, ['bc', 'bc'], ['-c', '-g', '-emit-llvm'], ['-w'],
                getArgFilter(Default.filterstr)))

        if opts.cp:
            commands.append(MakeCopyCommand(opts, job))

        for cmd in commands:
            RunCommand(cmd, opts.verbose)

        # }}}

    # PreprocessProject:
    if not jobList:
        return

    # Do sequential job:
    # Generate function mapping list
    if opts.fm:
        GenerateFunctionMappingList(opts, jobList)

    # Generate source file list
    if opts.ls:
        GenerateSourceFileList(opts, jobList)

    # Do parallel job:
    if 1 == opts.jobs:
        for i in jobList:
            jobRun(opts, i)
    else:
        pool = threadpool.ThreadPool(opts.jobs)
        reqs = threadpool.makeRequests(
                jobRun, [([opts, i], None) for i in jobList])
        for i in reqs:
            pool.putRequest(i)
        pool.wait()


class Filter:
    FilterType = namedtuple('FilterType',
            ['execfilter', 'abort', 'remove', 'output', 'source'])
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

    def MatchExec(self, exe):
        exe = os.path.basename(exe)
        for ef in self.filters.execfilter:
            if ef.fullmatch(exe):
                return exe
        return None

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
        return arg if match and (os.path.exists(arg) or arg.startswith('/tmp/')) else None

    def ParseExecutionCommands(self, exe):
        args = iter(exe.arguments)
        if not self.MatchExec(next(args)):
            return None
        self.exe = exe.arguments[0]
        self.pwd = exe.pwd
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
                        self.output = os.path.join(exe.pwd, target[-1])
                        if 1 != len(target):
                            self.arguments += target[:-1]
                        self.arguments.append(self.output)
                        continue
                if self.filters.source:
                    src = self.MatchSource(arg, exe.pwd)
                    if src:
                        self.files.append(src)
                        self.arguments.append(src)
                        continue
                # finally: add all un-matched arguments
                self.arguments.append(arg)
        return (self.exe, self.pwd, self.files, self.arguments, self.output,
                self.arguments.index(self.output) if self.output else None)


class CC1Filter(Filter):
    cc1filter = [re.compile('^([\w-]*g?cc|[\w-]*[gc]\+\+|clang(\+\+)?)(-[\d.]+)?$')]
    cc1abort = ['-E', '-cc1', '-cc1as', '-M', '-MM', '-###', '-fsyntax-only']
    cc1remove = [Filter.ParameterType(re.compile('^-[lL]'), 1),
            Filter.ParameterType(re.compile('^-(Wl,|Werror|Wall|M.?|shared|static)'), 0)]
    cc1output = Filter.ParameterType(re.compile('^-o'), 1)
    cc1source = Default.sourcefilter

    def __init__(self):
        super().__init__(Filter.FilterType(
            execfilter=CC1Filter.cc1filter, abort=CC1Filter.cc1abort,
            remove=CC1Filter.cc1remove, output=CC1Filter.cc1output,
            source=CC1Filter.cc1source))

    @staticmethod
    def MatchArguments(exe):
        Self = CC1Filter()
        result = Self.ParseExecutionCommands(exe)
        return CompilingCommands(compiler=result[0], directory=result[1],
                files=result[2], arguments=result[3], output=result[4],
                oindex=result[5], compilation='-c' in result[3]) if result else None


class ARFilter(Filter):
    arfilter = [re.compile('^[\w-]*ar(-[\d.]+)?$')]
    aroutput = Default.archivefilter
    arsource = Default.objectfilter

    def __init__(self):
        super().__init__(Filter.FilterType(
            execfilter=ARFilter.arfilter, abort=None, remove=None,
            output=ARFilter.aroutput, source=ARFilter.arsource))

    def MatchOutput(self, arg, i):
        return [arg] if self.filters.output.match(arg) else None

    @staticmethod
    def MatchArguments(exe):
        Self = ARFilter()
        result = Self.ParseExecutionCommands(exe)
        return LinkingCommands(linker=result[0], directory=result[1],
                files=result[2], arguments=result[3], output=result[4],
                oindex=result[5], archive=True) if result else None



class LDFilter(Filter):
    ldfilter = [re.compile('^[\w-]*ld(-[\d.]+)?$')]
    ldoutput = Filter.ParameterType(re.compile('^-o'), 1)
    ldsource = Default.linksourcefilter

    def __init__(self):
        super().__init__(Filter.FilterType(
            execfilter=LDFilter.ldfilter, abort=None, remove=None,
            output=LDFilter.ldoutput, source=LDFilter.ldsource))

    @staticmethod
    def MatchArguments(exe):
        Self = LDFilter()
        result = Self.ParseExecutionCommands(exe)
        return LinkingCommands(linker=result[0], directory=result[1],
                files=result[2], arguments=result[3], output=result[4],
                oindex=result[5], archive=False) if result else None

class AliasFilter:
    AliasFilterType = namedtuple('AliasFilterType', ['exe', 'input', 'output'])
    clangfilter = AliasFilterType(re.compile("^clang(-[\d.]+)?$"),
            re.compile("^-main-file-name$"), re.compile("^-o"))
    cc1filter = AliasFilterType(re.compile("^[\w-]*cc1(plus)?(-[\d.]+)?$"),
            re.compile("^-dumpbase$"), re.compile("^-o"))
    asfilter = AliasFilterType(re.compile("^[\w-]*as(-[\d.]+)?$"),
            Default.asmfilter, re.compile("^-o"))

    @staticmethod
    def MatchArguments(exe):
        argfilter, ifile, ofile = None, None, None
        args = iter(exe.arguments)
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
            imatch, omatch = argfilter.input.match(i), argfilter.output.match(i)
            if imatch:
                ifile = next(args) if '-' == imatch.group(0)[0] else imatch.group(0)
            elif omatch:
                ofile = next(args) if '-' == omatch.group(0)[0] else omatch.group(0)
        return {os.path.join(exe.pwd, ifile): [os.path.join(exe.pwd, ofile)]} \
                if ifile and ofile else None


def CatchCompilationDatabase(opts):
    def BuildProject(opts):
        print('Compiling the project: ' + ' '.join(opts.commands))
        outputdir = os.path.abspath(os.path.join(opts.output,
                time.strftime("%Y%m%d_%H%M%S.build", time.localtime())))
        os.makedirs(outputdir)

        environ = os.environ.copy()
        environ['LD_PRELOAD'] = Default.libpath
        environ['PANDA_TEMPORARY_OUTPUT_DIR'] = outputdir
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
                for rfile in cmd.files:
                    if rfile == ifile:
                        if not cmd.compilation:
                            arguments.insert(arguments.index(rfile), '-c')
                    else:
                        arguments.remove(rfile)
                ret.append({'output': output, 'directory': cmd.directory,
                    'file': ifile, 'arguments': arguments})
        with open(os.path.join(opts.output, 'compile_commands.json'), 'w') as f:
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
            for outputdir, dirs, files in os.walk(outputdir):
                for i in files:
                    i = os.path.join(outputdir, i)
                    yield json.load(open(i, 'r'))

        print('Generating "compile_commands.json" and "link_commands.json".')
        CompilationDatabase = list()
        LinkingDatabase = list()
        AliasDatabase = dict()
        for i in TraverseCommands(outputdir):
            exe = ExecCommands(**i)
            cd = CC1Filter.MatchArguments(exe)
            if cd and cd.files:
                CompilationDatabase.append(cd)
                continue
            ar = ARFilter.MatchArguments(exe)
            if ar and ar.files:
                LinkingDatabase.append(ar)
                AliasDatabase[ar.output] = ar.files
                continue
            ld = LDFilter.MatchArguments(exe)
            if ld and ld.files:
                LinkingDatabase.append(ld)
                AliasDatabase[ld.output] = ld.files
                continue
            al = AliasFilter.MatchArguments(exe)
            if al:
                for k in al:
                    if k in AliasDatabase:
                        AliasDatabase[k] += al[k]
                    else:
                        AliasDatabase[k] = al[k]
                continue
        AliasDatabase = SimplifyAlias(AliasDatabase)
        CDJson = ConstructCompilationDatabase(CompilationDatabase, AliasDatabase)
        LDJson = ConstructLinkingDatabase(LinkingDatabase, AliasDatabase)
        with open(os.path.join(outputdir, 'name_mapping.json'), 'w') as f:
            json.dump(AliasDatabase, f, indent=4)
        return (CompilationDatabase, LinkingDatabase, AliasDatabase, CDJson, LDJson)

    # CatchCompilationDatabase:
    CD, LD, AD, CJ, LJ = HandleCompileCommands(BuildProject(opts))
    return CJ


# LoadCompilationDatabase: load CompilationDatabase from input file
#
#   opts: opts object (refer to ParseArguments)
def LoadCompilationDatabase(opts):
    jobList = json.load(open(opts.compiling, 'r'))
    # convert 'command' to 'arguments'
    for i in jobList:
        if 'command' in i:
            i['arguments'] = shlex.split(i['command'])
            i.pop('command')
    return jobList


def main(args):
    opts = ParseArguments(args)
    CompilationDatabase = CatchCompilationDatabase(opts) if opts.build \
            else LoadCompilationDatabase(opts)
    PreprocessProject(opts, CompilationDatabase)


if '__main__' == __name__:
    main(sys.argv)
