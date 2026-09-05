# Spec

I want to start a project that lets me swap my windows pc from "gaming mode" to "tv mode". 

## Game mode

is at my desk, where

1. video output should go only to my two monitors,
2. audio should go to my headphones.

## Tv mode

is on my couch, and

1. video output should only go to my tv
2. audio output should only go to my speakers

### Strategy

#### Phase 1

First, I'd like to make a simple script (power shell? Python?) that can do each of those swaps individually. It should be able to swap from an unknown mode to tv mode, and swap from an unknown mode to game mode. The goal is reliability across any circumstance and to some extent reliablity.

This should be callable from an autohotkey script so that a simple key combo could do the swap for me.

#### Phase 2

Next I'd like to make this user friendly and installable as a single app/script. That way it is easy to customize for other users.

### Tech Stack

I have no idea what is good for this. My guess is that there is not an off-the-shelf open source solution that would work but perhaps https://github.com/Nuzair46/Monarch would work. If that just works, great, I'm happy to use that. But if not, I would prefer to do this in a real programming language rather than just powershell scripts. Ideally python since I'm used to it but if there's a language that can get us to a nice executable and installer in phase 2 perhaps that's better. I think it comes down to what works with the windows apis.

Eventually it would be nice to have a configurator UI that lets you pick the modes, the transitions, and eventually lets you set hotkeys, etc ourselves and not rely on autohotkey.

### Next steps

1. Research existing options
2. Propose tech stack for phase 1 and 2
3. Prototype solutions
4. make plan for phase 1 and tentative plan for phase 2
5. do phase 1
6. revise plan for phase 2
7. do plan for phase 2

### Notes

This must be a fully open source project that I hope to make GPL licensable. And I want heavy unit and end-to-end testing as feasible to ensure everything works.