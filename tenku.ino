/* Includes ------------------------------------------------------------------*/
#include "DEV_Config.h"
#include "EPD.h"
#include "GUI_Paint.h"
#include <stdlib.h>

#define MAX_LINES 20
#define MAX_CHARS_PER_LINE 50
#define LINE_HEIGHT 16

/* Entry point ---------------------------------------------------------------*/
void setup()
{
    printf("EPD_4IN2_V2_test Demo\r\n");
    DEV_Module_Init();

    printf("e-Paper Init and Clear...\r\n");
    EPD_4IN2_V2_Init();
    EPD_4IN2_V2_Clear();
    DEV_Delay_ms(500);

    // Create image buffer
    UBYTE *BlackImage;
    UWORD Imagesize = ((EPD_4IN2_V2_WIDTH % 8 == 0) ? (EPD_4IN2_V2_WIDTH / 8) : (EPD_4IN2_V2_WIDTH / 8 + 1)) * EPD_4IN2_V2_HEIGHT;
    if ((BlackImage = (UBYTE *)malloc(Imagesize)) == NULL)
    {
        printf("Failed to apply for black memory...\r\n");
        while (1)
            ;
    }
    Paint_NewImage(BlackImage, EPD_4IN2_V2_WIDTH, EPD_4IN2_V2_HEIGHT, 0, WHITE);

    // Your drawing code here
    // Iteration #1:
    // Paint_SelectImage(BlackImage);
    // Paint_Clear(WHITE);
    // Paint_DrawPoint, Paint_DrawLine, Paint_DrawString_EN, etc.

    // Iteration #2:
    // pass in image buffer (400x300)
    ProcessText(BlackImage, "test.txt");

    // Display on e-paper
    EPD_4IN2_V2_Display(BlackImage);
    DEV_Delay_ms(2000);

    // Cleanup
    printf("Goto Sleep...\r\n");
    EPD_4IN2_V2_Sleep();
    free(BlackImage);
    BlackImage = NULL;
}

void ProcessText(UBYTE *image, const char *filename)
{
    FILE *file = fopen(filename, "r");
    if (file == NULL)
    {
        printf("Failed to open file: %s\r\n", filename);
        return;
    }

    Paint_SelectImage(image);
    Paint_Clear(WHITE);

    char line[MAX_CHARS_PER_LINE + 1];
    int y_position = 10;
    int line_count = 0;


    // Read and draw each line
    while (fgets(line, sizeof(line), file) != NULL && line_count < MAX_LINES)
    {
        // Remove newline character
        line[strcspn(line, "\n")] = 0;

        printf("Line %d: %s\r\n", line_count, line);

        // Draw text on display
        Paint_DrawString_EN(10, y_position, line, &Font12, BLACK, WHITE);

        y_position += LINE_HEIGHT;
        line_count++;
    }

    
    fclose(file);

    printf("Total lines displayed: %d\r\n", line_count);

    // Display on e-paper
    EPD_4IN2_V2_Display(image);
    DEV_Delay_ms(2000);
}

/* Main loop -----------------------------------------------------------------*/
void loop()
{
    // Empty for ESP32
}