#define _GNU_SOURCE
#include <dirent.h>
#include <dlfcn.h>
#include <errno.h>
#include <pthread.h>
#include <spawn.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <unistd.h>

// version info {{{

#ifndef BUILD_TYPE
#if defined(__OPTIMIZE__) && __OPTIMIZE__
#define BUILD_TYPE "Release"
#else
#define BUILD_TYPE "Debug"
#endif
#endif
#ifndef BUILD_TIME
#define BUILD_TIME __DATE__ " - " __TIME__
#endif
#ifndef BUILD_BRANCH
#define BUILD_BRANCH "<unknown branch>"
#endif
#ifndef BUILD_COMMIT
#define BUILD_COMMIT "<unknown commit>"
#endif
#ifndef BUILD_COMPILER
#if defined(__clang__)
#define BUILD_COMPILER_TYPE "clang"
#elif defined(__GNUC__)
#define BUILD_COMPILER_TYPE "gcc"
#else
#define BUILD_COMPILER_TYPE "<unknown compiler>"
#endif
#ifdef __VERSION__
#define BUILD_COMPILER_VERSION __VERSION__
#else
#define BUILD_COMPILER_VERSION "<unknown version>"
#endif
#define BUILD_COMPILER BUILD_COMPILER_TYPE " - " BUILD_COMPILER_VERSION
#endif
#ifndef BUILD_SYSTEM
#if defined(linux) || defined(__linux__) || defined(__linux) || \
    defined(__gnu_linux__)
#define BUILD_SYSTEM "Linux"
#else
#define BUILD_SYSTEM "<unknown system>"
#endif
#endif

const int LOG_FD = STDERR_FILENO;

int version() {
  dprintf(LOG_FD,
          "LibPanda (%s - %s)\n"
          "Git checkout: %s - %s\n"
          "Environment : [%s] on %s\n",
          BUILD_TYPE, BUILD_TIME, BUILD_BRANCH, BUILD_COMMIT, BUILD_COMPILER,
          BUILD_SYSTEM);
  return 0;
}

// }}}

// utility functions {{{

void abort_if_failed(bool condition, const char *head, ...) {
  if (condition) return;
  dprintf(LOG_FD, "libpanda.so: ");
  va_list values;
  va_start(values, head);
  vdprintf(LOG_FD, head, values);
  va_end(values);
  if (errno) {
    dprintf(LOG_FD, ": ");
    perror(NULL);
  } else {
    // add the \n provided by perror
    dprintf(LOG_FD, "\n");
  }
  abort();
}

void f_auto_buffer_freer(char **p) {
  if (p) free((void *)*p);
}

#define auto_buffer __attribute__((cleanup(f_auto_buffer_freer)))

// }}}

// pre-process and post-process {{{

static int (*real_execvpe)(const char *, char *const *, char *const *) = NULL;
static int (*real_posix_spawnp)(pid_t *, const char *,
                                const posix_spawn_file_actions_t *,
                                const posix_spawnattr_t *attrp, char *const *,
                                char *const *) = NULL;

void load_real_function(void **var, const char *name) {
  if (*var) return;
  *var = dlsym(RTLD_NEXT, name);
  abort_if_failed(*var, "dlsym: cannot find function `%s'", name);
#ifdef DEBUG
  dprintf(LOG_FD, "function `%s' loaded: %p\n", name, *var);
#endif
}

const char *LD_PRELOAD = NULL;
const char *const LD_PRELOAD_NAME = "LD_PRELOAD";
const char *OUTPUT_DIR = NULL;
const char *const OUTPUT_DIR_NAME = "PANDA_TEMPORARY_OUTPUT_DIR";
const char *OUTPUT_TEMPLATE = "panda-exec.XXXXXX";
const char *const OUTPUT_TEMPLATE_NAME = "PANDA_TEMPORARY_OUTPUT_TEMPLATE";

void load_environment(const char **var, const char *name) {
  if (*var) return;
  *var = getenv(name);
  abort_if_failed(*var, "getenv: environment variable `%s' is not available",
                  name);
#ifdef DEBUG
  dprintf(LOG_FD, "%s = %s\n", name, *var);
#endif
}

// This function will be executed on every sub-processes when they are loading.
static void on_load() __attribute__((constructor));
static void on_load() {
  static bool inited = false;
  if (inited) return;

  static pthread_mutex_t mutex;
  pthread_mutex_lock(&mutex);

  if (inited) return;

  errno = 0;

  load_real_function((void **)&real_execvpe, "execvpe");
  load_real_function((void **)&real_posix_spawnp, "posix_spawnp");

  load_environment(&LD_PRELOAD, LD_PRELOAD_NAME);

#ifdef DEBUG
  dprintf(LOG_FD, "On loading process %d\n", getpid());
#else
  // Process output related job only in release version.

  load_environment(&OUTPUT_DIR, OUTPUT_DIR_NAME);

  // Check if output dir is ready to be written into.
  DIR *output_dir = opendir(OUTPUT_DIR);
  abort_if_failed(output_dir, "opendir: cannot open directory %s", OUTPUT_DIR);
  closedir(output_dir);

  const char *template = getenv(OUTPUT_TEMPLATE_NAME);
  if (template) OUTPUT_TEMPLATE = template;
#endif

  inited = true;
  pthread_mutex_unlock(&mutex);
}

static void on_unload() __attribute__((destructor));
static void on_unload() {}

// }}}

// log writter {{{

void write_log(int fd, const char *name, pid_t ppid, pid_t pid, const char *pwd,
               char *const argv[]) {
  dprintf(fd, "{");
  dprintf(fd, "\"method\": \"%s\", ", name);
  dprintf(fd, "\"ppid\": %d, ", ppid);
  dprintf(fd, "\"pid\": %d, ", pid);
  dprintf(fd, "\"pwd\": \"%s\", ", pwd);
  dprintf(fd, "\"arguments\": [");
  for (int i = 0; argv[i]; ++i) {
    dprintf(fd, "\"");
    for (int j = 0; argv[i][j]; ++j) {
      switch (argv[i][j]) {
        case '"':
          dprintf(fd, "\\\"");
          break;
        case '\\':
          dprintf(fd, "\\\\");
          break;
        case '\b':
          dprintf(fd, "\\b");
          break;
        case '\f':
          dprintf(fd, "\\f");
          break;
        case '\n':
          dprintf(fd, "\\n");
          break;
        case '\r':
          dprintf(fd, "\\r");
          break;
        default:
          dprintf(fd, "%c", argv[i][j]);
          break;
      }
    }
    dprintf(fd, argv[i + 1] ? "\", " : "\"");
  }
  dprintf(fd, "]}\n");
}

void f_auto_fd(int *p) {
  if (p) close(*p);
}

#define auto_fd __attribute__((cleanup(f_auto_fd)))

void f_log_exec(const char *name, char *const argv[]) {
  // Get pwd.
  auto_buffer char *pwd = get_current_dir_name();
  abort_if_failed(pwd, "get_current_dir_name");

#ifdef DEBUG
  int fd = LOG_FD;  // should not be closed!
#else
  // Create the output file in output dir.
  size_t len_output = strlen(OUTPUT_DIR);
  auto_buffer char *filename = malloc(len_output + strlen(OUTPUT_TEMPLATE) + 2);
  abort_if_failed(filename, "malloc");
  sprintf(filename, '/' == OUTPUT_DIR[len_output - 1] ? "%s%s" : "%s/%s",
          OUTPUT_DIR, OUTPUT_TEMPLATE);
  auto_fd int fd = mkstemp(filename);
#endif

  // Write log to the output file or stderr.
  write_log(fd, name, getppid(), getpid(), pwd, argv);
}

#define log_exec(...) f_log_exec(__PRETTY_FUNCTION__, __VA_ARGS__)

// }}}

// really execute the function {{{

int f_real_exec(const char *name, const char *file, char *const argv[],
                char *const envp[]) {
#ifdef DEBUG
  dprintf(LOG_FD, "real exec: %s\n", name);
#endif
  return real_execvpe(file, argv, envp);
}

#define real_exec(...) f_real_exec(__PRETTY_FUNCTION__, __VA_ARGS__)

int f_real_exec_posix_spawnp(const char *name, pid_t *pid, const char *file,
                             const posix_spawn_file_actions_t *file_actions,
                             const posix_spawnattr_t *attrp, char *const argv[],
                             char *const envp[]) {
#ifdef DEBUG
  dprintf(LOG_FD, "real exec: %s\n", name);
#endif
  return real_posix_spawnp(pid, file, file_actions, attrp, argv, envp);
}

#define real_exec_posix_spawnp(...) \
  f_real_exec_posix_spawnp(__PRETTY_FUNCTION__, __VA_ARGS__)

// }}}

// utility functions for stab catchers {{{

size_t count_args(va_list a) {
  size_t ret = 1;
  va_list args;
  va_copy(args, a);
  while (va_arg(args, const char *)) ++ret;
  va_end(args);
  return ret;
}

char **build_string_array(const char *first, va_list *strs) {
  size_t count = count_args(*strs) + 1;
  char **ret = calloc(count, sizeof(char *));
  ret[0] = strdup(first);
  for (int i = 1; i < count; ++i) {
    ret[i] = strdup(va_arg(*strs, const char *));
  }
  ret[count] = NULL;
  return ret;
}

void delete_string_array(char *argv[]) {
  for (int i = 0; argv[i]; ++i) free(argv[i]);
  free(argv);
}

// }}}

// stab catchers {{{

#define build_argv_list(first, ret) \
  va_list args;                     \
  va_start(args, first);            \
  char **ret = build_string_array(first, &args);

#define delete_argv_list(name)        \
  delete_string_array((char **)name); \
  va_end(args);

int execl(const char *path, const char *arg, ...) {
  build_argv_list(arg, argv);
  log_exec(argv);
  int ret = real_exec(path, argv, environ);
  delete_argv_list(argv);
  return ret;
}

int execlp(const char *file, const char *arg, ...) {
  build_argv_list(arg, argv);
  log_exec(argv);
  int ret = real_exec(file, argv, environ);
  delete_argv_list(argv);
  return ret;
}

int execle(const char *path, const char *arg, ... /*, char *const envp[] */) {
  build_argv_list(arg, argv);
  log_exec(argv);
  int ret = real_exec(path, argv, va_arg(args, char *const *));
  delete_argv_list(argv);
  return ret;
}

#undef build_argv_list
#undef delete_argv_list

int execv(const char *path, char *const argv[]) {
  log_exec(argv);
  return real_exec(path, argv, environ);
}

int execvp(const char *file, char *const argv[]) {
  log_exec(argv);
  return real_exec(file, argv, environ);
}

int execve(const char *file, char *const argv[], char *const envp[]) {
  log_exec(argv);
  return real_exec(file, argv, envp);
}

int execvpe(const char *file, char *const argv[], char *const envp[]) {
  log_exec(argv);
  return real_exec(file, argv, envp);
}

int posix_spawn(pid_t *pid, const char *path,
                const posix_spawn_file_actions_t *file_actions,
                const posix_spawnattr_t *attrp, char *const argv[],
                char *const envp[]) {
  log_exec(argv);
  return real_exec_posix_spawnp(pid, path, file_actions, attrp, argv, envp);
}

int posix_spawnp(pid_t *pid, const char *file,
                 const posix_spawn_file_actions_t *file_actions,
                 const posix_spawnattr_t *attrp, char *const argv[],
                 char *const envp[]) {
  log_exec(argv);
  return real_exec_posix_spawnp(pid, file, file_actions, attrp, argv, envp);
}

// }}}
