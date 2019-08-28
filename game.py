import math
import os
import asyncio
import json
import logging
from consts import Powerups

from map import Map, Tiles
from characters import Bomberman, Balloom, Character

logger = logging.getLogger('Game')
logger.setLevel(logging.DEBUG)

LIVES = 3
INITIAL_SCORE = 0
TIMEOUT = 3000 
MAX_HIGHSCORES = 10
GAME_SPEED = 10
MIN_BOMB_RADIUS = 3

class Bomb:
    def __init__(self, pos, radius, detonator=False):
        self._pos = pos
        self._timeout = radius+1
        self._radius = radius
        self._detonator = detonator

    def detonate(self):
        if self._detonator:
            self._timeout = 0

    @property
    def pos(self):
        return self._pos

    @property
    def timeout(self):
        return self._timeout

    @property
    def radius(self):
        return self._radius

    def update(self):
        self._timeout-=1/2

    def exploded(self):
        return not self._timeout > 0

    def in_range(self, character):
        px, py = self._pos
        if isinstance(character, Character):
            gx, gy = character.pos
        else:
            gx, gy = character


        return (px == gx or py == gy) and\
            (abs(px - gx) + abs(py - gy)) <= self._radius #we share a line/column and we are in distance d
    
    def __repr__(self):
        return self._pos


class Game:
    def __init__(self, level=1, lives=LIVES, timeout=TIMEOUT):
        logger.info("Game({}, {})".format(level, lives))
        self._running = False
        self._timeout = timeout
        self._score = 0
        self._state = {}
        self._initial_lives = lives
        self.map = Map(enemies=5) #TODO according to level spawn different enemies
        self._enemies = [Balloom(p) for p in self.map.enemies_spawn]
        
        self._highscores = [] 
        if os.path.isfile(f"{level}.score"):
            with open(f"{level}.score", 'r') as infile:
                self._highscores = json.load(infile)

    def info(self):
        return json.dumps({"level": self.map.level,
                           "size": self.map.size,
                           "map": self.map.map,
                           "enemies": [{'name': str(e), 'pos': e.pos} for e in self._enemies],
                           "fps": GAME_SPEED,
                           "timeout": TIMEOUT,
                           "lives": LIVES,
                           "score": self.score,
                           "highscores": self.highscores,
                            })

    @property
    def running(self):
        return self._running

    @property
    def score(self):
        return self._score

    @property
    def highscores(self):
        return self._highscores

    def start(self, player_name):
        logger.debug("Reset world")
        self._player_name = player_name
        self._running = True
        
        self.map = Map()
        self._step = 0
        self._bomberman = Bomberman(self.map.bomberman_spawn, self._initial_lives)
        self._bombs = []
        self._powerups = []
        self._bonus = []
        self._exit = []
        self._lastkeypress = "" 
        self._score = INITIAL_SCORE 
        self._bomb_radius = 3

    def stop(self):
        logger.info("GAME OVER")
        self.save_highscores()
        self._running = False

    def quit(self):
        logger.debug("Quit")
        self._running = False

    def save_highscores(self):
        #update highscores
        logger.debug("Save highscores")
        logger.info("FINAL SCORE <%s>: %s", self._player_name, self.score)
        self._highscores.append((self._player_name, self.score))
        self._highscores = sorted(self._highscores, key=lambda s: -1*s[1])[:MAX_HIGHSCORES]
    
        with open(f"{self.map._level}.score", 'w') as outfile:
            json.dump(self._highscores, outfile)

    def keypress(self, key):
        self._lastkeypress = key

    def update_bomberman(self):
        try:
            if self._lastkeypress.isupper():
                #Parse action
                if self._lastkeypress == 'B' and len(self._bombs) < self._bomberman.powers.count(Powerups.Bombs) + 1:
                    self._bombs.append(Bomb(self._bomberman.pos, MIN_BOMB_RADIUS+self._bomberman.flames())) # must be dependent of powerup
            else:
                #Update position
                new_pos = self.map.calc_pos(self._bomberman.pos, self._lastkeypress) #don't bump into stones/walls
                if new_pos not in [b.pos for b in self._bombs]: #don't pass over bombs
                    self._bomberman.pos = new_pos
                for pos, _type in self._powerups: #consume powerups
                    if new_pos == pos:
                        self._bomberman.powerup(_type)
                        self._powerups.remove((pos, _type))

        except AssertionError:
            logger.error("Invalid key <%s> pressed. Valid keys: w,a,s,d A B", self._lastkeypress)
        finally:
            self._lastkeypress = "" #remove inertia

        if len(self._enemies) == 0 and self._bomberman.pos == self._exit:
            logger.info("Level completed")
            self.stop()

    def kill_bomberman(self):
        logger.info("bomberman has died on step: {}".format(self._step))
        self._bomberman.kill()
        logger.debug(f"bomberman has now {self._bomberman.lives} lives")
        if self._bomberman.lives > 0:
            logger.debug("RESPAWN")
            self._bomberman.respawn()
        else:
            self.stop()

    def collision(self):
        for e in self._enemies:
            if e.pos == self._bomberman.pos:
                self.kill_bomberman()

    def explode_bomb(self):
        for bomb in self._bombs[:]:
            bomb.update()
            if bomb.exploded():
                logger.debug("BOOM")
                if bomb.in_range(self._bomberman):
                    self.kill_bomberman()

                for wall in self.map.walls[:]:
                    if bomb.in_range(wall):
                        logger.debug(f"Destroying wall @{wall}")
                        self.map.remove_wall(wall)
                        if self.map.exit_door == wall:
                            self._exit = wall
                        if self.map.powerup == wall:
                            self._powerups.append((wall, Powerups.Flames))

                for enemy in self._enemies[:]:
                    if bomb.in_range(enemy):
                        logger.debug(f"killed enemy @{enemy}")
                        self._score += enemy.points()
                        self._enemies.remove(enemy)

                self._bombs.remove(bomb)

    async def next_frame(self):
        await asyncio.sleep(1./GAME_SPEED)

        if not self._running:
            logger.info("Waiting for player 1")
            return

        self._step += 1
        if self._step == self._timeout:
            self.stop()

        if self._step % 100 == 0:
            logger.debug("[{}] SCORE {} - LIVES {}".format(self._step, self._score, self._bomberman.lives))

        self.explode_bomb()  
        self.update_bomberman()

        for enemy in self._enemies:
            enemy.move(self.map)

        self.collision()
        self._state = {"step": self._step,
                       "timeout": self._timeout,
                       "player": self._player_name,
                       "score": self._score,
                       "lives": self._bomberman.lives,
                       "bomberman": self._bomberman.pos,
                       "bombs": [(b.pos, b.timeout, b.radius) for b in self._bombs],
                       "enemies": [{'name': str(e), 'pos': e.pos} for e in self._enemies],
                       "walls": self.map.walls,
                       "powerups": [(p, Powerups(n).name) for p, n in self._powerups], 
                       "bonus": self._bonus,
                       "exit": self._exit,
                       }

    @property
    def state(self):
        #logger.debug(self._state)
        return json.dumps(self._state)
