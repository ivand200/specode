---
name: Terminal Silver
colors:
  surface: '#fbf8fa'
  surface-dim: '#dcd9db'
  surface-bright: '#fbf8fa'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f6f3f4'
  surface-container: '#f0edee'
  surface-container-high: '#eae7e9'
  surface-container-highest: '#e4e2e3'
  on-surface: '#1b1b1d'
  on-surface-variant: '#44474c'
  inverse-surface: '#303031'
  inverse-on-surface: '#f3f0f1'
  outline: '#75777d'
  outline-variant: '#c5c6cc'
  surface-tint: '#555f70'
  primary: '#212b3a'
  on-primary: '#ffffff'
  primary-container: '#374151'
  on-primary-container: '#a3adc0'
  inverse-primary: '#bdc7db'
  secondary: '#a93349'
  on-secondary: '#ffffff'
  secondary-container: '#fe7488'
  on-secondary-container: '#730425'
  tertiary: '#362811'
  on-tertiary: '#ffffff'
  tertiary-container: '#4e3e25'
  on-tertiary-container: '#c0a989'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#d9e3f7'
  primary-fixed-dim: '#bdc7db'
  on-primary-fixed: '#121c2a'
  on-primary-fixed-variant: '#3d4757'
  secondary-fixed: '#ffdadc'
  secondary-fixed-dim: '#ffb2b9'
  on-secondary-fixed: '#400010'
  on-secondary-fixed-variant: '#891933'
  tertiary-fixed: '#f8dfbc'
  tertiary-fixed-dim: '#dbc3a2'
  on-tertiary-fixed: '#261905'
  on-tertiary-fixed-variant: '#55442b'
  background: '#fbf8fa'
  on-background: '#1b1b1d'
  surface-variant: '#e4e2e3'
typography:
  display:
    fontFamily: Inter
    fontSize: 36px
    fontWeight: '600'
    lineHeight: '1.2'
    letterSpacing: -0.02em
  h1:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: '1.3'
    letterSpacing: -0.01em
  h2:
    fontFamily: Inter
    fontSize: 20px
    fontWeight: '500'
    lineHeight: '1.4'
  body:
    fontFamily: Inter
    fontSize: 15px
    fontWeight: '400'
    lineHeight: '1.6'
  body-sm:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '400'
    lineHeight: '1.5'
  code:
    fontFamily: Space Grotesk
    fontSize: 14px
    fontWeight: '400'
    lineHeight: '1.5'
  label-mono:
    fontFamily: Space Grotesk
    fontSize: 11px
    fontWeight: '600'
    lineHeight: '1'
    letterSpacing: 0.05em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  base: 4px
  xs: 8px
  sm: 16px
  md: 24px
  lg: 40px
  xl: 64px
  gutter: 20px
  margin: 32px
---

## Brand & Style

This design system is built on the principles of **Technical Minimalism** and **Functional Precision**. It aims to evoke the feeling of a premium, high-end hardware interface—clean, cold, and exceptionally efficient. The aesthetic is designed for developers and technical power users who require a distraction-free environment that feels both sophisticated and airy.

The style leverages a "Silver" metaphor through the use of tonal gray layering and crisp, hairline dividers. It avoids the heavy shadows of traditional skuomorphism in favor of a flat, architectural layout. By stripping away all blue-based neutrals, the system achieves a unique, grounded warmth through its Deep Ink text and Coral highlights, ensuring a distinctive presence in a market saturated with blue-tinted interfaces.

## Colors

The color palette is strictly curated to maintain a "Silver" tech aesthetic. The foundation is **Cool Light Gray (#F3F4F6)**, which provides a bright, expansive canvas. Navigation and structural elements use **Charcoal (#374151)** for grounded authority.

**Deep Ink (#111827)** is used for all primary text to ensure maximum legibility and a sense of "printed" permanence. **Subtle Coral (#FB7185)** is the sole accent, reserved strictly for interactive highlights, notifications, or critical "action" states. All grays must remain strictly neutral or cool-gray to avoid any blue bias, ensuring the Coral pop remains vibrant and purposeful.

## Typography

Typography in this design system prioritizes utility and modernism. **Inter** serves as the primary workhorse for the UI, chosen for its exceptional legibility and neutral character. It should be typeset with tight letter-spacing for headlines and generous leading for body text to maintain the "airy" feel.

**Space Grotesk** is utilized for "Mono accents," such as terminal outputs, code snippets, and metadata labels. This introduces a technical, geometric edge that reinforces the developer-centric nature of the product. Use the `label-mono` style for small descriptors and category tags to add a rhythmic, organized feel to the layout.

## Layout & Spacing

This design system employs a **Fixed Grid** model for core desktop views (1280px max-width) and a fluid 12-column grid for smaller viewports. The spacing rhythm is strictly based on a **4px baseline**, ensuring that every element—from the height of a button to the padding of a card—is a multiple of four.

Layouts should lean heavily on whitespace (the `lg` and `xl` tokens) to create a sense of calm. Content is grouped into logical modules separated by thin dividers rather than large gaps, creating a structured, "integrated" terminal environment.

## Elevation & Depth

To maintain its minimalist aesthetic, this design system rejects heavy shadows. Depth is instead communicated through **Tonal Layers** and **Low-Contrast Outlines**.

1.  **Level 0 (Base):** The #F3F4F6 background.
2.  **Level 1 (Surface):** Elements like sidebars or cards use a pure white (#FFFFFF) or slightly lighter gray surface to suggest a slight lift.
3.  **Borders:** Use 1px "Hairline" borders (#D1D5DB) to define boundaries. 
4.  **Interaction:** When an item is hovered, it should not rise; instead, it should receive a subtle background tint change or a 1px Coral left-border accent.

This "flat-stack" approach ensures the UI feels like a single, cohesive piece of glass or metal rather than floating paper layers.

## Shapes

The shape language is disciplined and professional. A **Soft (4px)** corner radius is applied to all primary UI components like buttons, input fields, and small cards. This provides just enough approachability to feel modern without losing the precision associated with a terminal environment.

Larger containers or sections may use `rounded-lg` (8px) for a slightly softer appearance, but elements should never become "pill-shaped" unless they are purely decorative tags or status chips. Sharp internal corners within nested components are encouraged to maintain a tight, technical look.

## Components

### Buttons
Primary buttons use the Charcoal background with white text. Secondary buttons are ghost-style with a Charcoal border. The Coral accent is reserved for "Action" buttons (e.g., Run, Deploy).

### Input Fields
Inputs should have a white background, a 1px neutral border, and use the Mono font for the input text. The focus state replaces the neutral border with a 1px Charcoal border—no glows or heavy rings.

### Terminal Blocks
Code or output containers should use a slightly darker gray background (#E5E7EB) with a 1px border. They should always use the `code` typography style.

### Chips & Tags
Used for metadata, these should be small, rectangular (4px radius), using a light gray background and the `label-mono` type style.

### Progress & Highlights
Use the Coral color (#FB7185) for progress bars, cursor carets in code editors, and active navigation indicators. This singular use of color ensures the eye is immediately drawn to the "active" part of the interface.