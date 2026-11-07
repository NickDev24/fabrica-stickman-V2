# Character asset credits

## Supplied stylized office bases and 50-look catalog

| Output                 | Original creator / source                                                    | License |
| ---------------------- | ---------------------------------------------------------------------------- | ------- |
| `eunchae-office.glb`   | Quaternius, Animated Women Pack: Smooth Female Casual, Alternative and Dress | CC0 1.0 |
| `office-male-base.glb` | Quaternius, Animated Man Pack: ClothedMan                                    | CC0 1.0 |

- [Animated Women Pack](https://quaternius.com/packs/animatedwomen.html)
- [Animated Man Pack](https://quaternius.com/packs/animatedman.html)
- [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/)

Women license is supplied alongside the source models. The official Animated
Man page links to the exact user-supplied Drive folder and declares CC0.
Original sources are kept outside this repository (`art/characters/supplied-bases/` in the maintainers' working tree) and are available on request.

Eunchae adaptations: combined bob hair, jacket, shirt, midi skirt and shoes;
ivory, beige and green office palette; continuous skirt deformation bones;
constraint-baked idle/walk/sit clips and uniform scene scaling. Male adaptations:
office palette, uniform scale, resampled walk loop and authored seated pose.
The 50 files under `office/` derive from the same corresponding male/female CC0
sources. Catalog adaptations include individual skin/hair/office palettes,
garment hems and lapels, hairstyles, bone-attached bags, glasses and accessories,
and an upright male idle pose. Builders are in `tools/characters/`; original sources and catalog manifests are
kept outside the repository by the maintainers.
These GLBs contain no MPFB or MakeHuman assets. No endorsement is implied.

## Earlier MPFB comparison model

`eunchae-mpfb.glb` is an adapted character assembled with MPFB 2.0.17 and
MakeHuman community assets. It is not a likeness of an actor or drama character.

| Component                                                                                                             | Source / author                                                                                      | License   |
| --------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- | --------- |
| Human topology, game_engine rig, young Asian female skin, bob01 hair, low-poly eyes, eyebrow001, eyelashes01, shoes02 | MakeHuman Community system assets; Data Collection AB, Joel Palmius, Jonas Hauquier and contributors | CC0 1.0   |
| Basic tucked T-shirt, long full skirt                                                                                 | Margaret Toigo (MRT / MargaretToigo), shirts01 and skirts01 packs                                    | CC0 1.0   |
| Long open-front cardigan                                                                                              | Mindfront (Sweden), shirts02 pack                                                                    | CC BY 4.0 |

Cardigan modifications: fitted to the Eunchae body, cropped to hip length,
reweighted hem, recolored ivory, textures resized/compressed, exported as a
skinned glTF mesh. Other adaptations include stylized head proportions, matte
skin, brown hair, narrower green skirt, and original idle/walk/sit animation.
The attribution requirement for Mindfront's cardigan remains applicable when
redistributing the combined model. No endorsement by the original authors is
implied.

- [MakeHuman system assets](https://static.makehumancommunity.org/assets/assetpacks/makehuman_system_assets.html)
- [Shirts01](https://static.makehumancommunity.org/assets/assetpacks/shirts01.html)
- [Skirts01](https://static.makehumancommunity.org/assets/assetpacks/skirts01.html)
- [Mindfront cardigan in Shirts02](https://static.makehumancommunity.org/assets/assetpacks/shirts02.html)
- [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/)
- [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
- [MPFB source](https://github.com/makehumancommunity/mpfb2), revision
  `437dd513888a92399d1d3200d2e80859fae55abc` (GPL-3.0-or-later tooling;
  its code is not included in this GLB).
