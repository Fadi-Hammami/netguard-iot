/* =========================================================================
 * Test isole - Afficheur Grove 4 Digits (module TM1637) - MSP432P401R
 * =========================================================================
 *
 * Materiel :
 *   - LaunchPad MSP-EXP432P401R
 *   - Grove BoosterPack
 *   - Afficheur Grove 4 Digits (TM1637) branche sur J14 (connecteur Digital)
 *
 * Brochage :
 *   - J14 (Digital) -> P2.4 (CLK) et P2.6 (DIO)
 * VCC et GND sont deja cables par le connecteur Grove, seuls les 2 fils
 * de signal CLK/DIO sont utilises par le microcontroleur.
 *
 * Ce programme ne fait QUE piloter l'afficheur : il compte de 0000 a 9999
 * en boucle, un increment toutes les 500 ms, afin de verifier que tous
 * les segments et les 4 digits fonctionnent correctement, independamment
 * du DHT22 ou du buzzer.
 *
 * ========================================================================= */

#include "msp.h"
#include <stdint.h>

/* ------------------------------------------------------------------- */
/*  Constantes                                                          */
/* ------------------------------------------------------------------- */
#define CPU_FREQ_HZ     12000000UL

#define TM_CLK_PIN      0x10   /* P2.4 -> BIT4  (J14 CLK) */
#define TM_DIO_PIN      0x40   /* P2.6 -> BIT6  (J14 DIO) */

/* ------------------------------------------------------------------- */
/*  1) Horloge : DCO a 12 MHz, MCLK = SMCLK = DCO                        */
/* ------------------------------------------------------------------- */
void Clock_Init12MHz(void)
{
    CS->KEY  = 0x695A;
    CS->CTL0 = 0;
    CS->CTL0 = CS_CTL0_DCORSEL_3;
    CS->CTL1 = CS_CTL1_SELA_2 | CS_CTL1_SELS_3 | CS_CTL1_SELM_3;
    CS->KEY  = 0;
}

/* ------------------------------------------------------------------- */
/*  2) Base de temps (SysTick) pour delais en microsecondes/millisecondes*/
/* ------------------------------------------------------------------- */
void SysTick_start(void)
{
    SysTick->CTRL = 0;
    SysTick->LOAD = 0x00FFFFFF;
    SysTick->VAL  = 0;
    SysTick->CTRL = SysTick_CTRL_CLKSOURCE_Msk | SysTick_CTRL_ENABLE_Msk;
}

uint32_t SysTick_elapsedUs(uint32_t depart)
{
    uint32_t maintenant = SysTick->VAL;
    uint32_t ticks;

    if (depart >= maintenant)
    {
        ticks = depart - maintenant;
    }
    else
    {
        ticks = (0x00FFFFFF - maintenant) + depart;
    }
    return ticks / (CPU_FREQ_HZ / 1000000UL);
}

void delay_us(uint32_t us)
{
    uint32_t depart = SysTick->VAL;
    while (SysTick_elapsedUs(depart) < us)
    {
        /* attente active */
    }
}

void delay_ms(uint32_t ms)
{
    while (ms--)
    {
        delay_us(1000);
    }
}

/* ------------------------------------------------------------------- */
/*  3) Pilote de l'afficheur 4 Digits (module TM1637) sur P2.4/P2.6 (J14)*/
/* ------------------------------------------------------------------- */
static void TM_dioOut(void)  { P2->DIR |=  TM_DIO_PIN; }
static void TM_dioIn(void)   { P2->DIR &= ~TM_DIO_PIN; P2->REN |= TM_DIO_PIN; P2->OUT |= TM_DIO_PIN; }
static void TM_dioHigh(void) { P2->OUT |=  TM_DIO_PIN; }
static void TM_dioLow(void)  { P2->OUT &= ~TM_DIO_PIN; }
static void TM_clkHigh(void) { P2->OUT |=  TM_CLK_PIN; }
static void TM_clkLow(void)  { P2->OUT &= ~TM_CLK_PIN; }

void TM1637_Init(void)
{
    P2->SEL0 &= ~(TM_CLK_PIN | TM_DIO_PIN);
    P2->SEL1 &= ~(TM_CLK_PIN | TM_DIO_PIN);
    P2->DIR  |=  (TM_CLK_PIN | TM_DIO_PIN);
    TM_clkHigh();
    TM_dioHigh();
}

static void TM_start(void)
{
    TM_dioOut();
    TM_dioHigh();
    TM_clkHigh();
    delay_us(3);
    TM_dioLow();
}

static void TM_stop(void)
{
    TM_clkLow();
    delay_us(3);
    TM_dioLow();
    delay_us(3);
    TM_clkHigh();
    delay_us(3);
    TM_dioHigh();
}

static void TM_writeByte(uint8_t data)
{
    uint8_t i;

    for (i = 0; i < 8; i++)
    {
        TM_clkLow();
        if (data & 0x01) TM_dioHigh(); else TM_dioLow();
        delay_us(3);
        TM_clkHigh();
        delay_us(3);
        data >>= 1;
    }

    /* bit ACK renvoye par le module (on ne bloque pas si absent) */
    TM_clkLow();
    TM_dioIn();
    delay_us(3);
    TM_clkHigh();
    delay_us(3);
    TM_clkLow();
    TM_dioOut();
}

static const uint8_t TM_digits[11] =
{
    0x3F, 0x06, 0x5B, 0x4F, 0x66,   /* 0 1 2 3 4 */
    0x6D, 0x7D, 0x07, 0x7F, 0x6F,   /* 5 6 7 8 9 */
    0x00                             /* vide      */
};

/* Affiche un nombre de 0 a 9999 sur les 4 digits (zeros non significatifs
 * remplaces par des espaces). point_central allume le double-point. */
void TM1637_displayNumber(int nombre, uint8_t point_central)
{
    uint8_t d0, d1, d2, d3;
    int v = nombre;

    d3 = (uint8_t)(v % 10); v /= 10;
    d2 = (uint8_t)(v % 10); v /= 10;
    d1 = (uint8_t)(v % 10); v /= 10;
    d0 = (uint8_t)(v % 10);

    TM_start();
    TM_writeByte(0x40);         /* mode ecriture, adresse auto-incrementee */
    TM_stop();

    TM_start();
    TM_writeByte(0xC0);         /* adresse du 1er digit */
    TM_writeByte(TM_digits[d0]);
    TM_writeByte(TM_digits[d1] | (point_central ? 0x80 : 0x00));
    TM_writeByte(TM_digits[d2]);
    TM_writeByte(TM_digits[d3]);
    TM_stop();

    TM_start();
    TM_writeByte(0x88 | 0x07);  /* ecran allume, luminosite max */
    TM_stop();
}

/* Test additionnel : allume tous les segments de tous les digits (utile
 * pour verifier rapidement qu'aucun segment n'est mort). */
void TM1637_testTousSegments(void)
{
    TM_start();
    TM_writeByte(0x40);
    TM_stop();

    TM_start();
    TM_writeByte(0xC0);
    TM_writeByte(0xFF);
    TM_writeByte(0xFF);
    TM_writeByte(0xFF);
    TM_writeByte(0xFF);
    TM_stop();

    TM_start();
    TM_writeByte(0x88 | 0x07);
    TM_stop();
}

/* ------------------------------------------------------------------- */
/*  Programme principal                                                  */
/* ------------------------------------------------------------------- */
int main(void)
{
    int compteur = 0;

    WDT_A->CTL = 0x5A80;        /* arrete le chien de garde */

    Clock_Init12MHz();
    SysTick_start();
    TM1637_Init();

    /* --- Etape 1 : test visuel de tous les segments pendant 2s --- */
    TM1637_testTousSegments();
    delay_ms(2000);

    /* --- Etape 2 : comptage continu pour verifier chaque digit --- */
    while (1)
    {
        TM1637_displayNumber(compteur, (compteur % 2 == 0));  /* point clignote */

        compteur++;
        if (compteur > 9999)
        {
            compteur = 0;
        }

        delay_ms(500);
    }
}
