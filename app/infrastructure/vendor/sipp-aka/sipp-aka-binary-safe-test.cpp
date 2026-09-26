#include "aka_binary_param.hpp"

#include <array>
#include <cstddef>
#include <cstring>
#include <iostream>

static bool check(const char *hex, const unsigned char *expected, std::size_t length)
{
    char escaped[257] = {};
    std::size_t decoded = 0;
    if (!sipp_aka::hex_to_escaped(hex, escaped, sizeof escaped, &decoded)
            || decoded != length || std::strlen(escaped) != length * 4) {
        return false;
    }
    for (std::size_t i = 0; i < length; ++i) {
        if (escaped[i * 4] != '\\' || escaped[i * 4 + 1] != 'x') return false;
        const int high = sipp_aka::hex_digit(escaped[i * 4 + 2]);
        const int low = sipp_aka::hex_digit(escaped[i * 4 + 3]);
        if (high < 0 || low < 0 || static_cast<unsigned char>((high << 4) | low) != expected[i]) {
            return false;
        }
    }
    return true;
}

int main()
{
    const std::array<unsigned char, 8> binary = {0x00, 0x5b, 0x5c, 0x7f, 0x80, 0xff, 0x20, 0x41};
    const unsigned char odd[] = {0x0a};
    char too_small[4] = {};
    std::size_t decoded = 0;
    if (!check("005B5C7F80FF2041", binary.data(), binary.size())
            || !check("A", odd, 1)
            || sipp_aka::hex_to_escaped("005B", too_small, sizeof too_small, &decoded)) {
        std::cerr << "FAIL: synthetic AKA byte preservation\n";
        return 1;
    }
    std::cout << "PASS: synthetic AKA byte preservation (including NUL and delimiter)\n";
}
