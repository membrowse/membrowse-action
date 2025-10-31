/*
 * cpp_program.cpp - C++ program for testing symbol demangling
 *
 * This program contains various C++ features that produce mangled symbols:
 * - Classes and methods
 * - Namespaces
 * - Templates
 * - Constructors and destructors
 * - Overloaded functions
 *
 * Note: Uses static allocation to avoid requiring C++ runtime (new/delete)
 */

#include <stdint.h>

// Namespace for testing namespaced symbols
namespace Hardware {
    namespace Peripherals {

        // Class with methods
        class UART {
        private:
            uint32_t baudrate;
            uint8_t status;

        public:
            // Constructor
            UART() : baudrate(0), status(0) {}
            UART(uint32_t baud) : baudrate(baud), status(0) {}

            // Destructor
            ~UART() {
                status = 0;
            }

            // Methods
            void init();
            void transmit(const char* data, uint32_t length);
            uint8_t getStatus() const;

            // Static method
            static uint32_t calculateChecksum(const uint8_t* data, uint32_t length);
        };

        // Class with template (using fixed-size array)
        template<typename T, uint32_t SIZE>
        class Buffer {
        private:
            T data[SIZE];
            uint32_t size;

        public:
            Buffer() : size(SIZE) {
                for (uint32_t i = 0; i < size; i++) {
                    data[i] = T();
                }
            }

            void write(uint32_t index, T value) {
                if (index < size) {
                    data[index] = value;
                }
            }

            T read(uint32_t index) const {
                if (index < size) {
                    return data[index];
                }
                return T();
            }

            uint32_t getSize() const { return size; }
        };

    } // namespace Peripherals
} // namespace Hardware

// Global variables
static uint32_t global_counter = 0;

// UART method implementations
void Hardware::Peripherals::UART::init() {
    status = 0x01; // Ready
    baudrate = 115200;
}

void Hardware::Peripherals::UART::transmit(const char* data, uint32_t length) {
    for (uint32_t i = 0; i < length; i++) {
        volatile char byte = data[i];
        byte++; // Prevent optimization
    }
    status |= 0x02; // TX complete
}

uint8_t Hardware::Peripherals::UART::getStatus() const {
    return status;
}

uint32_t Hardware::Peripherals::UART::calculateChecksum(const uint8_t* data, uint32_t length) {
    uint32_t sum = 0;
    for (uint32_t i = 0; i < length; i++) {
        sum += data[i];
    }
    return sum;
}

// Function overloading
namespace Math {

    int add(int a, int b) {
        return a + b;
    }

    float add(float a, float b) {
        return a + b;
    }

    double add(double a, double b) {
        return a + b;
    }

    // Template function
    template<typename T>
    T multiply(T a, T b) {
        return a * b;
    }

    // Explicit template instantiations to ensure they're in the binary
    template int multiply<int>(int, int);
    template float multiply<float>(float, float);

} // namespace Math

// Class with inheritance (without virtual destructor to avoid runtime deps)
namespace System {

    class Device {
    protected:
        uint32_t device_id;

    public:
        Device() : device_id(0) {}
        Device(uint32_t id) : device_id(id) {}
        // Non-virtual destructor to avoid operator delete requirement
        ~Device() {}

        // Regular method instead of pure virtual to avoid vtable issues
        void reset() {
            device_id = 0;
        }

        uint32_t getId() const { return device_id; }
    };

    class Timer : public Device {
    private:
        uint32_t counter;

    public:
        Timer() : Device(0), counter(0) {}
        Timer(uint32_t id) : Device(id), counter(0) {}

        void reset() {
            counter = 0;
            Device::reset();
        }

        void increment() {
            counter++;
        }

        uint32_t getValue() const {
            return counter;
        }
    };

} // namespace System

// extern "C" function to avoid mangling (for testing mixed C/C++)
extern "C" {
    void c_style_function(void) {
        global_counter++;
    }

    int main(void) {
        // Local instances (to avoid static initialization issues)
        Hardware::Peripherals::UART uart_instance;
        Hardware::Peripherals::Buffer<uint8_t, 256> rx_buffer;
        System::Timer system_timer;

        // Initialize UART instance
        uart_instance.init();

        // Use various functions
        const char* msg = "Hello from C++!";
        uart_instance.transmit(msg, 15);

        // Use overloaded functions
        int int_sum = Math::add(5, 10);
        float float_sum = Math::add(3.14f, 2.86f);

        // Use template functions
        int product = Math::multiply<int>(4, 7);

        // Use buffer
        rx_buffer.write(0, 'A');
        rx_buffer.write(1, 'B');
        uint8_t first_byte = rx_buffer.read(0);

        // Use timer
        for (int i = 0; i < 100; i++) {
            system_timer.increment();
        }

        // Calculate checksum
        uint8_t test_data[] = {0x01, 0x02, 0x03, 0x04};
        uint32_t checksum = Hardware::Peripherals::UART::calculateChecksum(test_data, 4);

        // Call C-style function
        c_style_function();

        // Prevent optimization
        volatile uint32_t result = int_sum + float_sum + product + first_byte +
                                   checksum + system_timer.getValue();
        result++;

        return 0;
    }
}
