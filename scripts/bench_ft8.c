// ft8_lib in-process benchmark: decode one 15s WAV N times, report per-decode wall time.
// Mirrors demo/decode_ft8.c structure (same candidate/LDPC pipeline).
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <stdbool.h>
#include <time.h>

#include <ft8/decode.h>
#include <ft8/encode.h>
#include <ft8/message.h>
#include <common/common.h>
#include <common/wave.h>
#include <common/monitor.h>

#define LOG_LEVEL LOG_INFO
#include <ft8/debug.h>

static const int kMin_score = 10;
static const int kMax_candidates = 140;
static const int kLDPC_iterations = 25;
static const int kMax_decoded_messages = 50;
static const int kFreq_osr = 2;
static const int kTime_osr = 2;

#define CALLSIGN_HASHTABLE_SIZE 256
static struct {
    char callsign[12];
    uint32_t hash;
} callsign_hashtable[CALLSIGN_HASHTABLE_SIZE];
static int callsign_hashtable_size;

static void hashtable_add(const char* callsign, uint32_t hash) {
    uint16_t hash10 = (hash >> 12) & 0x3FFu;
    int idx_hash = (hash10 * 23) % CALLSIGN_HASHTABLE_SIZE;
    while (callsign_hashtable[idx_hash].callsign[0] != '\0') {
        if (((callsign_hashtable[idx_hash].hash & 0x3FFFFFu) == hash) && (0 == strcmp(callsign_hashtable[idx_hash].callsign, callsign))) {
            callsign_hashtable[idx_hash].hash &= 0x3FFFFFu;
            return;
        }
        idx_hash = (idx_hash + 1) % CALLSIGN_HASHTABLE_SIZE;
    }
    callsign_hashtable_size++;
    strncpy(callsign_hashtable[idx_hash].callsign, callsign, 11);
    callsign_hashtable[idx_hash].callsign[11] = '\0';
    callsign_hashtable[idx_hash].hash = hash;
}

static bool hashtable_lookup(ftx_callsign_hash_type_t hash_type, uint32_t hash, char* callsign) {
    uint8_t hash_shift = (hash_type == FTX_CALLSIGN_HASH_10_BITS) ? 12 : (hash_type == FTX_CALLSIGN_HASH_12_BITS ? 10 : 0);
    uint16_t hash10 = (hash >> (12 - hash_shift)) & 0x3FFu;
    int idx_hash = (hash10 * 23) % CALLSIGN_HASHTABLE_SIZE;
    while (callsign_hashtable[idx_hash].callsign[0] != '\0') {
        if (((callsign_hashtable[idx_hash].hash & 0x3FFFFFu) >> hash_shift) == hash) {
            strcpy(callsign, callsign_hashtable[idx_hash].callsign);
            return true;
        }
        idx_hash = (idx_hash + 1) % CALLSIGN_HASHTABLE_SIZE;
    }
    callsign[0] = '\0';
    return false;
}

static ftx_callsign_hash_interface_t hash_if = {
    .lookup_hash = hashtable_lookup,
    .save_hash = hashtable_add
};

static int decode(const monitor_t* mon) {
    const ftx_waterfall_t* wf = &mon->wf;
    ftx_candidate_t candidate_list[kMax_candidates];
    int num_candidates = ftx_find_candidates(wf, kMax_candidates, candidate_list, kMin_score);
    int num_decoded = 0;
    ftx_message_t decoded[kMax_decoded_messages];
    ftx_message_t* decoded_hashtable[kMax_decoded_messages];
    for (int i = 0; i < kMax_decoded_messages; ++i) decoded_hashtable[i] = NULL;

    for (int idx = 0; idx < num_candidates; ++idx) {
        const ftx_candidate_t* cand = &candidate_list[idx];
        ftx_message_t message;
        ftx_decode_status_t status;
        if (!ftx_decode_candidate(wf, cand, kLDPC_iterations, &message, &status))
            continue;
        int idx_hash = message.hash % kMax_decoded_messages;
        bool found_empty = false, found_dup = false;
        do {
            if (decoded_hashtable[idx_hash] == NULL) { found_empty = true; }
            else if ((decoded_hashtable[idx_hash]->hash == message.hash) && (0 == memcmp(decoded_hashtable[idx_hash]->payload, message.payload, sizeof(message.payload)))) { found_dup = true; }
            else { idx_hash = (idx_hash + 1) % kMax_decoded_messages; }
        } while (!found_empty && !found_dup);
        if (found_empty) {
            memcpy(&decoded[idx_hash], &message, sizeof(message));
            decoded_hashtable[idx_hash] = &decoded[idx_hash];
            ++num_decoded;
            char text[FTX_MAX_MESSAGE_LENGTH];
            ftx_message_offsets_t offsets;
            ftx_message_decode(&message, &hash_if, text, &offsets);
            float freq_hz = (mon->min_bin + cand->freq_offset + (float)cand->freq_sub / wf->freq_osr) / mon->symbol_period;
            float time_sec = (cand->time_offset + (float)cand->time_sub / wf->time_osr) * mon->symbol_period;
            printf("   %+05.1f %+4.2f %4.0f ~  %s\n", cand->score * 0.5f, time_sec, freq_hz, text);
        }
    }
    return num_decoded;
}

extern size_t g_peak;
int main(int argc, char** argv) {
    if (argc < 3) { fprintf(stderr, "usage: %s in.wav repeats\n", argv[0]); return 2; }
    int repeats = atoi(argv[2]);

    float signal[15 * 12000];
    int num_samples = 15 * 12000, sample_rate = 0;
    if (load_wav(signal, &num_samples, &sample_rate, argv[1]) < 0) {
        printf("ERROR: cannot load %s\n", argv[1]);
        return 1;
    }
    printf("loaded %d samples @ %d Hz\n", num_samples, sample_rate);

    monitor_t mon;
    monitor_config_t mon_cfg = {
        .f_min = 200, .f_max = 3000, .sample_rate = sample_rate,
        .time_osr = kTime_osr, .freq_osr = kFreq_osr,
        .protocol = FTX_PROTOCOL_FT8,
    };

    int total = 0;
    clock_t t0 = clock();
    for (int i = 0; i < repeats; ++i) {
        monitor_init(&mon, &mon_cfg);
        for (int frame_pos = 0; frame_pos + mon.block_size <= num_samples; frame_pos += mon.block_size)
            monitor_process(&mon, signal + frame_pos);
        total += decode(&mon);
        monitor_free(&mon);
    }
    double sec = (double)(clock() - t0) / CLOCKS_PER_SEC;
    printf("REPEATS %d TOTAL_MSGS %d WALL %.3fs PER_DECODE %.1fms monitor_size %zu wf_size %zu cand_stack %zu\n",
           repeats, total, sec, sec * 1000.0 / repeats,
           sizeof(monitor_t), sizeof(ftx_waterfall_t), kMax_candidates * sizeof(ftx_candidate_t));
    return 0;
}
