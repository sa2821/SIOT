import esptool

def main():
    # Specify the port where your ESP32 is connected
    port = '/dev/tty.usbserial-0001'

    # Initialize the esptool command line interface
    esptool.main([
        '--port', port,         # Specify the ESP32 port
        '--baud', '115200',     # Set baud rate (optional; default is 115200)
        'erase_flash'           # Replace with 'write_flash' to program the ESP32
    ])

if __name__ == '__main__':
    main()