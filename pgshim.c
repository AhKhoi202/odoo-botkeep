/* LD_PRELOAD shim for PostgreSQL tools. initdb (src/common/username.c) looks up the
   effective uid with getpwuid_r and aborts when the container uid (998) has no
   passwd entry. When the real lookup finds nothing, return a synthetic entry whose
   name comes from PG_OS_USER (default "odoo"). */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <pwd.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/types.h>

static const char *os_user(void)
{
    const char *n = getenv("PG_OS_USER");
    return (n && *n) ? n : "odoo";
}

static const char *os_home(void)
{
    const char *h = getenv("HOME");
    return (h && *h) ? h : "/tmp";
}

int getpwuid_r(uid_t uid, struct passwd *pwd, char *buf, size_t buflen, struct passwd **result)
{
    static int (*real)(uid_t, struct passwd *, char *, size_t, struct passwd **);
    const char *name = os_user();
    const char *home = os_home();
    size_t need = strlen(name) + 1 + 2 + 1 + strlen(home) + 1 + strlen("/bin/sh") + 1;
    char *p;
    int rc;

    if (!real)
        real = (int (*)(uid_t, struct passwd *, char *, size_t, struct passwd **))
               dlsym(RTLD_NEXT, "getpwuid_r");
    rc = real ? real(uid, pwd, buf, buflen, result) : ENOENT;
    if (rc != 0)
        return rc;
    if (*result)
        return 0;

    if (buflen < need)
        return ERANGE;
    p = buf;
    pwd->pw_name = p;   strcpy(p, name);  p += strlen(name) + 1;
    pwd->pw_passwd = p; strcpy(p, "x");   p += 2;
    pwd->pw_uid = uid;
    pwd->pw_gid = getgid();
    pwd->pw_gecos = p;  *p++ = '\0';
    pwd->pw_dir = p;    strcpy(p, home);  p += strlen(home) + 1;
    pwd->pw_shell = p;  strcpy(p, "/bin/sh");
    *result = pwd;
    return 0;
}

struct passwd *getpwuid(uid_t uid)
{
    static struct passwd *(*real)(uid_t);
    static struct passwd fake;
    static char name[64];
    static char home[256];
    struct passwd *found;

    if (!real)
        real = (struct passwd *(*)(uid_t))dlsym(RTLD_NEXT, "getpwuid");
    found = real ? real(uid) : NULL;
    if (found)
        return found;
    strncpy(name, os_user(), sizeof(name) - 1);
    strncpy(home, os_home(), sizeof(home) - 1);
    fake.pw_name = name;
    fake.pw_passwd = (char *)"x";
    fake.pw_uid = uid;
    fake.pw_gid = getgid();
    fake.pw_gecos = (char *)"";
    fake.pw_dir = home;
    fake.pw_shell = (char *)"/bin/sh";
    return &fake;
}
