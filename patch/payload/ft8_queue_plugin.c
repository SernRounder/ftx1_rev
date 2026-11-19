#include "ft8_plugin.h"

void ft8_queue_entry(const struct ft8_plugin_host *host,
                     const struct ft8_full_peer *peer, char *line)
{
    char *p = host->append(host->append(line, peer->call), " ");
    p = host->report(p, peer->db);
    *p++ = ' ';
    p = host->append(host->number(p, peer->hz), "Hz");
    if (peer->km != FT8_DISTANCE_UNKNOWN)
        p = host->append(host->number(host->append(p, " "), peer->km), "km");
    *p = 0;
}
