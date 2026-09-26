// 3GPP TS 35.208, section 4.3.1, Test Set 1 (public conformance data).
#include "milenage.h"
extern "C" {
#include "rijndael.h"
}
#include <cstdio>
#include <cstdlib>
#include <cstring>

static void decode(const char *hex, uint8_t *out, size_t size)
{
    for (size_t i = 0; i < size; ++i) {
        unsigned int value;
        if (std::sscanf(hex + 2 * i, "%2x", &value) != 1) std::abort();
        out[i] = static_cast<uint8_t>(value);
    }
}

static void expect(const char *label, const uint8_t *actual, const char *hex, size_t size)
{
    uint8_t expected[16] = {};
    decode(hex, expected, size);
    if (std::memcmp(actual, expected, size) != 0) {
        std::fprintf(stderr, "FAIL: %s\n", label);
        std::exit(1);
    }
}

int main()
{
    uint8_t k[16], rand[16], sqn[6], amf[2], op[16], opc[16];
    decode("465b5ce8b199b49faa5f0a2ee238a6bc", k, 16);
    decode("23553cbe9637a89d218ae64dae47bf35", rand, 16);
    decode("ff9bb4d0b607", sqn, 6);
    decode("b9b9", amf, 2);
    decode("cdc202d5123e20f62b6d676ac72cb318", op, 16);
    decode("cd63cb71954a9f4e48a5994e37a02baf", opc, 16);

    uint8_t computed[16];
    RijndaelKeySchedule(k);
    ComputeOPc(computed, op);
    expect("OPc derivation", computed, "cd63cb71954a9f4e48a5994e37a02baf", 16);

    for (int direct = 0; direct <= 1; ++direct) {
        uint8_t *input = direct ? opc : op;
        uint8_t mac[8], mac_s[8], res[8], ck[16], ik[16], ak[6], ak_s[6];
        f1(k, rand, sqn, amf, mac, input, direct);
        f1star(k, rand, sqn, amf, mac_s, input, direct);
        f2345(k, rand, res, ck, ik, ak, input, direct);
        f5star(k, rand, ak_s, input, direct);
        expect("MAC-A", mac, "4a9ffac354dfafb3", 8);
        expect("MAC-S", mac_s, "01cfaf9ec4e871e9", 8);
        expect("RES", res, "a54211d5e3ba50bf", 8);
        expect("AK", ak, "aa689c648370", 6);
        expect("CK", ck, "b40ba9a3c58b2a05bbf0d987b21bf8cb", 16);
        expect("IK", ik, "f769bcd751044604127672711c6d3441", 16);
        expect("AK-S", ak_s, "451e8beca43b", 6);
    }

    // Treating an OPc as OP must not accidentally produce the valid response.
    uint8_t wrong_res[8], ck[16], ik[16], ak[6], expected_res[8];
    f2345(k, rand, wrong_res, ck, ik, ak, opc, 0);
    decode("a54211d5e3ba50bf", expected_res, 8);
    if (std::memcmp(wrong_res, expected_res, 8) == 0) std::abort();
    std::puts("PASS: TS 35.208 OP and OPc vectors; double derivation rejected");
}
